from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

logger = logging.getLogger("cryptoguardian.pattern_tracker")

# VLM price levels can shift slightly between scans. These thresholds are
# deliberately conservative: most shared levels should be within 2.5%, and
# none of the compared levels should differ by more than 5%.
LEVEL_MEDIAN_TOLERANCE = 0.025
LEVEL_MAX_TOLERANCE = 0.05
MIN_COMMON_LEVELS = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _normalise(value: Any) -> str:
    return " ".join(
        str(value or "").strip().lower().replace("_", " ").split()
    )


def _direction(pattern: dict[str, Any]) -> str:
    return _normalise(pattern.get("direction"))


def _anchor(pattern: dict[str, Any]) -> str | None:
    value = (
        pattern.get("formation_start_time")
        or pattern.get("start_time")
        or pattern.get("anchor_candle_time")
    )
    return str(value) if value is not None else None


def _levels(pattern: dict[str, Any]) -> dict[str, float]:
    raw = pattern.get("key_levels")
    if not isinstance(raw, dict):
        return {}

    result: dict[str, float] = {}
    for key, value in raw.items():
        try:
            number = float(value)
            if number > 0:
                result[str(key)] = number
        except (TypeError, ValueError):
            continue
    return result


def _level_similarity(
    first: dict[str, float],
    second: dict[str, float],
) -> tuple[bool, float | None]:
    """Compare shared named price levels using relative percentage distance."""
    common = set(first) & set(second)
    if len(common) < MIN_COMMON_LEVELS:
        return False, None

    differences: list[float] = []
    for key in common:
        scale = max(abs(first[key]), abs(second[key]), 1e-12)
        differences.append(abs(first[key] - second[key]) / scale)

    median_difference = median(differences)
    maximum_difference = max(differences)

    matched = (
        median_difference <= LEVEL_MEDIAN_TOLERANCE
        and maximum_difference <= LEVEL_MAX_TOLERANCE
    )
    return matched, median_difference


class PatternTracker:
    """Persist unique VLM formations and update repeated detections.

    Preferred VLM fields:
      - name
      - direction
      - formation_start_time (if the VLM can reliably provide it)
      - key_levels with level_high, level_low, trigger_level,
        and invalidation_level

    If both records have formation anchors, the anchors must match.
    Otherwise, at least two shared named price levels are compared.
    """

    def __init__(
        self,
        state_file: str | Path,
        duplicate_window_minutes: int = 240,
    ) -> None:
        self.state_file = Path(state_file)
        self.window = timedelta(minutes=duplicate_window_minutes)
        self.lock = threading.RLock()
        self.records: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        with self.lock:
            if not self.state_file.exists():
                return
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                records = data.get("records", {}) if isinstance(data, dict) else {}
                self.records = records if isinstance(records, dict) else {}
            except (OSError, json.JSONDecodeError):
                logger.exception(
                    "Could not load pattern tracker state: %s",
                    self.state_file,
                )

    def _save(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.state_file.with_suffix(
                self.state_file.suffix + ".tmp"
            )
            payload = {
                "updated_at": _now().isoformat(),
                "records": self.records,
            }
            temp_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            temp_file.replace(self.state_file)
        except OSError:
            logger.exception(
                "Could not save pattern tracker state: %s",
                self.state_file,
            )

    def _remove_expired(self) -> None:
        cutoff = _now() - self.window
        expired: list[str] = []

        for record_id, record in self.records.items():
            last_seen = _parse_time(record.get("last_seen"))
            if last_seen is None or last_seen < cutoff:
                expired.append(record_id)

        for record_id in expired:
            self.records.pop(record_id, None)

    def _find_match(
        self,
        symbol: str,
        timeframe: str,
        pattern: dict[str, Any],
    ) -> str | None:
        name = _normalise(pattern.get("name"))
        direction = _direction(pattern)
        anchor = _anchor(pattern)
        levels = _levels(pattern)
        now = _now()

        candidates: list[tuple[float, datetime, str]] = []

        for record_id, record in self.records.items():
            if record.get("symbol") != symbol:
                continue
            if record.get("timeframe") != timeframe:
                continue
            if _normalise(record.get("name")) != name:
                continue

            old_direction = _direction(record)
            # If both detections provide direction, it must agree.
            if direction and old_direction and direction != old_direction:
                continue

            last_seen = _parse_time(record.get("last_seen"))
            if last_seen is None or now - last_seen > self.window:
                continue

            old_anchor = _anchor(record)
            if anchor and old_anchor:
                if anchor == old_anchor:
                    return record_id
                # Different explicit formation starts mean different setups.
                continue

            old_levels = _levels(record)
            is_similar, distance = _level_similarity(levels, old_levels)
            if is_similar and distance is not None:
                candidates.append((distance, last_seen, record_id))

        # Prefer the closest price-level match; use recency as a tie-breaker.
        if candidates:
            candidates.sort(key=lambda item: (item[0], -item[1].timestamp()))
            return candidates[0][2]

        return None

    def update(
        self,
        symbol: str,
        timeframe: str,
        detected_patterns: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge one scan and return active unique patterns for this market."""
        timestamp = _now().isoformat()

        with self.lock:
            self._remove_expired()

            for pattern in detected_patterns:
                if not isinstance(pattern, dict):
                    continue

                name = str(pattern.get("name") or "").strip()
                if not name:
                    continue

                match_id = self._find_match(symbol, timeframe, pattern)

                if match_id:
                    record = self.records[match_id]
                    record.update({
                        key: value
                        for key, value in pattern.items()
                        if value is not None
                    })
                    record.update({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "last_seen": timestamp,
                        "detections": int(record.get("detections", 1)) + 1,
                        "tracker_status": "updated_existing",
                    })
                    logger.info(
                        "DUPLICATE PATTERN UPDATED | %s | %s | detections=%s",
                        symbol,
                        record.get("name"),
                        record["detections"],
                    )
                else:
                    record_id = str(uuid.uuid4())
                    record = dict(pattern)
                    record.update({
                        "pattern_id": record_id,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "first_seen": timestamp,
                        "last_seen": timestamp,
                        "detections": 1,
                        "tracker_status": "new",
                    })
                    self.records[record_id] = record
                    logger.info(
                        "NEW UNIQUE PATTERN | %s | %s",
                        symbol,
                        record.get("name"),
                    )

            self._save()

            active = [
                dict(record)
                for record in self.records.values()
                if record.get("symbol") == symbol
                and record.get("timeframe") == timeframe
            ]
            return sorted(
                active,
                key=lambda item: item.get("first_seen", ""),
            )
