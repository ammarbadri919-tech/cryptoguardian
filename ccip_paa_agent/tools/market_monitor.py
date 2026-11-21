from __future__ import annotations
from tools.chart_generator import generate_chart_base64, clear_old_charts
from tools.VLM_chart_analysis import analyze_pre_generated_chart
from tools.pattern_tracker import PatternTracker
import base64
import concurrent.futures
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any
from tools.llm_advisor import ask_llm_advisor

import ccxt
import pandas as pd

from tools.chart_generator import generate_chart_base64, clear_old_charts
from tools.VLM_chart_analysis import analyze_pre_generated_chart


BASE_DIR = Path(__file__).resolve().parent.parent
WATCHLIST_FILE = BASE_DIR / "selected_coins.csv"

TIMEFRAME = "15m"
OHLCV_LIMIT = 300

CHART_UPDATE_INTERVAL_SECONDS = 3
SCAN_INTERVAL_SECONDS = 120

QUOTE_CURRENCIES = ("USDT",)
MAX_VLM_WORKERS = 3

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

REPORT_ROOT = BASE_DIR / "runtime" / "pattern_reports"

PATTERN_TRACKER = PatternTracker(
    state_file=BASE_DIR / "runtime" / "pattern_tracker" / "patterns.json",
    duplicate_window_minutes=240
)

IST = ZoneInfo("Asia/Kolkata")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cryptoguardian.market_monitor")

executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=MAX_VLM_WORKERS,
    thread_name_prefix="VLM",
)

# Independent scan schedule for each exchange/symbol.
last_scan_time: dict[tuple[str, str], float] = {}
scans_in_flight: set[tuple[str, str]] = set()
active_candle_start: dict[tuple[str, str], int] = {}
scan_lock = threading.Lock()


@dataclass
class MarketSnapshot:
    exchange: str
    symbol: str
    timeframe: str
    fetched_at: str
    last_price: float | None
    candle_timestamp: int
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    candle_is_probably_closed: bool


# ---------------------------------------------------------------------------
# Exchange and watchlist
# ---------------------------------------------------------------------------

def display_gemini_decision(symbol, decision):
    action = decision.get("decision", "UNAVAILABLE").upper()
    confidence = decision.get("decision_confidence", 0) * 100
    reason = decision.get("reason", "No reason provided.")

    print("\n" + "=" * 42)
    print("          CRYPTOGUARDIAN AI")
    print("=" * 42)
    print(f"Symbol: {symbol}")
    print("Agent: Gemini Decision Agent")
    print("-" * 42)
    print(f"Decision: {action}")
    print(f"Confidence: {confidence:.2f}%")
    print(f"\nReason: {reason}")
    print("=" * 42 + "\n")
def create_exchange() -> dict[str, Any]:
    return {
        "binance": ccxt.binance({
            "enableRateLimit": True,
            "timeout": 20000,
            "options": {"defaultType": "spot"},
        })
    }


def load_exchange_markets(exchanges: dict[str, Any]) -> None:
    for name, exchange in exchanges.items():
        try:
            exchange.load_markets()
            logger.info("%s: loaded %d markets", name, len(exchange.markets))
        except Exception:
            logger.exception("%s: could not load markets", name)


def load_watchlist(filepath: Path = WATCHLIST_FILE) -> list[str]:
    if not filepath.exists():
        logger.error("Watchlist file not found: %s", filepath)
        return []

    try:
        df = pd.read_csv(filepath)
        if "symbol" not in df.columns:
            logger.error("Watchlist CSV must contain a 'symbol' column.")
            return []

        bases: list[str] = []
        for value in df["symbol"].dropna().astype(str):
            item = value.strip().upper()
            if item:
                base = item.split("/")[0].strip()
                if base and base not in bases:
                    bases.append(base)

        logger.info("Loaded watchlist bases: %s", bases)
        return bases

    except Exception:
        logger.exception("Could not read watchlist: %s", filepath)
        return []


def supported_pairs(exchange: Any, base: str) -> list[str]:
    pairs: list[str] = []
    for quote in QUOTE_CURRENCIES:
        symbol = f"{base}/{quote}"
        market = exchange.markets.get(symbol)
        if market and market.get("active", True) and market.get("spot", True):
            pairs.append(symbol)
    return pairs


def to_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        result = float(value)
        return result if pd.notna(result) else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def fetch_market_snapshot(
    exchange_name: str,
    exchange: Any,
    symbol: str,
) -> tuple[MarketSnapshot | None, pd.DataFrame | None]:
    """Fetch OHLCV and ticker data, then refresh the forming candle's price.

    The ticker updates the latest candle close/high/low between OHLCV updates.
    Volume remains the value returned by Binance's OHLCV endpoint.
    """
    try:
        candles = exchange.fetch_ohlcv(
            symbol,
            timeframe=TIMEFRAME,
            limit=OHLCV_LIMIT,
        )
        if not candles:
            logger.warning("No OHLCV data returned for %s", symbol)
            return None, None

        columns = ["timestamp", "open", "high", "low", "close", "volume"]
        all_df = pd.DataFrame(candles, columns=columns)

        ticker = exchange.fetch_ticker(symbol)
        last_price = to_float(ticker.get("last"))

        # Refresh the latest/forming candle with the most recent ticker price.
        if last_price is not None and not all_df.empty:
            last_index = all_df.index[-1]
            current_high = to_float(all_df.at[last_index, "high"])
            current_low = to_float(all_df.at[last_index, "low"])

            all_df.at[last_index, "close"] = last_price
            all_df.at[last_index, "high"] = (
                max(current_high, last_price)
                if current_high is not None else last_price
            )
            all_df.at[last_index, "low"] = (
                min(current_low, last_price)
                if current_low is not None else last_price
            )

        latest = all_df.iloc[-1]
        snapshot = MarketSnapshot(
            exchange=exchange_name,
            symbol=symbol,
            timeframe=TIMEFRAME,
            fetched_at=datetime.now(IST).isoformat(timespec="seconds"),
            last_price=last_price,
            candle_timestamp=int(latest["timestamp"]),
            open=to_float(latest["open"]),
            high=to_float(latest["high"]),
            low=to_float(latest["low"]),
            close=to_float(latest["close"]),
            volume=to_float(latest["volume"]),
            candle_is_probably_closed=False,
        )
        return snapshot, all_df

    except Exception:
        logger.exception("%s: failed to fetch data for %s", exchange_name, symbol)
        return None, None


# ---------------------------------------------------------------------------
# Runtime chart and JSON history
# ---------------------------------------------------------------------------

def save_chart_image(symbol: str, image_b64: str, candle_timestamp: int) -> None:
    """Save a chart snapshot under the current 15-minute cycle (IST)."""
    try:
        cycle_start = datetime.fromtimestamp(candle_timestamp / 1000, tz=timezone.utc).astimezone(IST)
        safe_symbol = symbol.replace("/", "_").replace(":", "_")
        image_dir = (
            BASE_DIR / "runtime" / "market_history" / safe_symbol
            / cycle_start.strftime("%Y-%m-%d")
            / cycle_start.strftime("%H-%M")
        )
        image_dir.mkdir(parents=True, exist_ok=True)
        now_ist = datetime.now(IST)
        image_path = image_dir / f"{now_ist.strftime('%H-%M-%S-%f')}_chart.png"
        with image_path.open("wb") as image_file:
            image_file.write(base64.b64decode(image_b64))
        logger.info("RUNTIME CHART SAVED | %s", image_path)
    except Exception:
        logger.exception("Could not save runtime chart for %s", symbol)


def delete_runtime_chart_history(symbol: str) -> None:
    """Delete PNG snapshots from the previous cycle; JSON reports are untouched."""
    safe_symbol = symbol.replace("/", "_").replace(":", "_")
    symbol_dir = BASE_DIR / "runtime" / "market_history" / safe_symbol
    if not symbol_dir.exists():
        return
    deleted = 0
    for png_file in symbol_dir.rglob("*_chart.png"):
        try:
            png_file.unlink()
            deleted += 1
        except FileNotFoundError:
            pass
        except Exception:
            logger.exception("Could not delete old cycle chart %s", png_file)
    # Remove empty date/cycle folders, but leave any JSON-containing folders/files.
    for folder in sorted((p for p in symbol_dir.rglob("*") if p.is_dir()), key=lambda x: len(x.parts), reverse=True):
        try:
            folder.rmdir()
        except OSError:
            pass
    logger.info("15M CYCLE RESET | %s | deleted %d old runtime chart PNGs", symbol, deleted)


def save_latest_report(report: dict[str, Any]) -> None:
    """Save timestamped JSON reports permanently; cycle resets never delete JSON."""
    try:
        safe_symbol = report["symbol"].replace("/", "_").replace(":", "_")
        report_dir = REPORT_ROOT / safe_symbol / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(IST).strftime("%Y-%m-%d_%H-%M-%S-%f")
        report_file = report_dir / f"{timestamp}.json"
        with report_file.open("w", encoding="utf-8") as file:
            json.dump(report, file, indent=2, ensure_ascii=False, default=str)
        logger.info("NEW JSON REPORT SAVED | %s", report_file)
    except Exception:
        logger.exception("Failed to save JSON report for %s", report.get("symbol"))

def process_vlm_result_in_background(
    future: concurrent.futures.Future,
    snapshot: MarketSnapshot,
    candles_df: pd.DataFrame,
    candle_key: tuple[str, str] | None,
    cycle_completed: bool = False,
    cycle_start_ist: str | None = None,
) -> None:
    """Process Nemotron results, track unique patterns, and get Gemini's decision."""
    try:
        vlm_result = future.result()
        logger.info(
    "NEMOTRON ANALYSIS COMPLETED | %s | Patterns: %d",
    snapshot.symbol,
    len(vlm_result.get("patterns_found", []))
    if isinstance(vlm_result, dict) else 0,
)
        

        if not isinstance(vlm_result, dict):
            logger.warning("Invalid VLM result for %s", snapshot.symbol)
            return

        # Prepare detected patterns for the Pattern Tracker.
        patterns = []

        for pattern in vlm_result.get("patterns_found", []):
            if not isinstance(pattern, dict):
                continue

            patterns.append({
                "name": pattern.get("name"),
                "type": pattern.get("type"),
                "direction": pattern.get("direction"),

                "status": pattern.get("formation_state"),
                    "formation_start_time": pattern.get("formation_start_time"),

                "formation_state": pattern.get("formation_state"),
                "key_levels": pattern.get("key_levels"),
                "confidence": pattern.get("confidence"),
                "evidence": pattern.get("evidence"),
                 "missing_conditions": pattern.get("missing_conditions", []),

            
            })


        # Track unique patterns and update repeated detections.
        # Patterns detected in the latest VLM scan
        current_detections = patterns

# All active patterns, including historical detections
        tracked_patterns = PATTERN_TRACKER.update(
         symbol=snapshot.symbol,
         timeframe=snapshot.timeframe,
        detected_patterns=current_detections,
)

        # Build the VLM report.
        report = {
            "symbol": snapshot.symbol,
            "exchange": snapshot.exchange,
            "timeframe": snapshot.timeframe,
            "fetched_at": datetime.now(IST).isoformat(),
            "cycle_completed": cycle_completed,
            "cycle_start_ist": cycle_start_ist,
            "market_snapshot": asdict(snapshot),
            "vlm_analysis": {
                "current_detections": current_detections,
                "tracked_patterns": tracked_patterns,

                "market_structure": vlm_result.get("market_structure"),
                "overall_visual_bias": vlm_result.get("overall_visual_bias"),
                "breakout_status": vlm_result.get("breakout_status"),
                "confidence": vlm_result.get("confidence"),
                "visual_evidence": vlm_result.get("visual_evidence"),
                "limitations": vlm_result.get("limitations", []),
            },
        }

        # Prepare input for Gemini Decision 1.
        # Prepare input for Gemini Decision 1.
        vlm_report = {
             "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,

             "current_detections": current_detections,
              "tracked_patterns": tracked_patterns,

            "market_structure": vlm_result.get("market_structure"),
            "overall_visual_bias": vlm_result.get("overall_visual_bias"),
            "breakout_status": vlm_result.get("breakout_status"),
            "confidence": vlm_result.get("confidence"),
            "visual_evidence": vlm_result.get("visual_evidence"),
            "limitations": vlm_result.get("limitations", []),
}
        logger.info(
            "GEMINI DECISION STARTED | %s | Patterns: %d",
            snapshot.symbol,
            len(current_detections),
        )

    
        # Ask Gemini to evaluate all unique patterns together.
        try:
            print(f">>> GEMINI REQUEST STARTED: {snapshot.symbol} <<<", flush=True)


            decision = ask_llm_advisor(
    vlm_report=vlm_report,
    market_context=asdict(snapshot),
    has_open_position=False,
)
            print(f">>> GEMINI RESPONSE RECEIVED: {snapshot.symbol} <<<", flush=True)

            
            

            display_gemini_decision(snapshot.symbol, decision)

            report["gemini_decision"] = decision

            logger.info(
                "GEMINI DECISION | %s | %s | Confidence: %s",
                snapshot.symbol,
                decision["decision"],
                decision.get("decision_confidence"),
            )

        except Exception as e:
            logger.exception(
                "Gemini decision failed for %s",
                snapshot.symbol,
            )

            report["gemini_decision"] = {
                "decision": "UNAVAILABLE",
                "reason": "Gemini API request failed",
            }

        # Save the complete report.
        save_latest_report(report)

        logger.info(
            "LIVE PATTERN REPORT | %s\n%s",
            snapshot.symbol,
            json.dumps(report, indent=2, default=str),
        )

    except Exception:
        logger.exception(
            "Background VLM task failed for %s",
            snapshot.symbol,
        )

    finally:
        if candle_key is not None:
            with scan_lock:
                scans_in_flight.discard(candle_key)





def fast_loop(exchanges: dict[str, Any], watchlist: list[str]) -> None:
    """Refresh charts every loop; scan every minute and finalize each 15m candle."""
    for base in watchlist:
        for exchange_name, exchange in exchanges.items():
            if not getattr(exchange, "markets", None):
                continue
            for symbol in supported_pairs(exchange, base):
                candle_key = (exchange_name, symbol)
                try:
                    snapshot, all_df = fetch_market_snapshot(exchange_name, exchange, symbol)
                    if snapshot is None or all_df is None:
                        continue

                    current_candle_start = snapshot.candle_timestamp
                    previous_candle_start = active_candle_start.get(candle_key)

                    # A Binance 15m candle timestamp changes at the exact 15m boundary.
                    if previous_candle_start is not None and current_candle_start != previous_candle_start:
                        previous_start_ist = datetime.fromtimestamp(
                            previous_candle_start / 1000, tz=timezone.utc
                        ).astimezone(IST)
                        logger.info(
                            "15M CANDLE CLOSED | %s | cycle=%s to %s",
                            symbol,
                            previous_start_ist.strftime("%H:%M"),
                            datetime.fromtimestamp(current_candle_start / 1000, tz=timezone.utc).astimezone(IST).strftime("%H:%M"),
                        )

                        # Final scan uses only candles older than the newly opened candle.
                        closed_df = all_df[all_df["timestamp"] < current_candle_start].copy()
                        if not closed_df.empty:
                            final_image = generate_chart_base64(symbol, closed_df)
                            if final_image:
                                final_snapshot = MarketSnapshot(
                                    exchange=snapshot.exchange,
                                    symbol=snapshot.symbol,
                                    timeframe=snapshot.timeframe,
                                    fetched_at=datetime.now(IST).isoformat(timespec="seconds"),
                                    last_price=to_float(closed_df.iloc[-1]["close"]),
                                    candle_timestamp=int(closed_df.iloc[-1]["timestamp"]),
                                    open=to_float(closed_df.iloc[-1]["open"]),
                                    high=to_float(closed_df.iloc[-1]["high"]),
                                    low=to_float(closed_df.iloc[-1]["low"]),
                                    close=to_float(closed_df.iloc[-1]["close"]),
                                    volume=to_float(closed_df.iloc[-1]["volume"]),
                                    candle_is_probably_closed=True,
                                )
                                final_future = executor.submit(
                                    analyze_pre_generated_chart,
                                    symbol,
                                    final_image,
                                    TIMEFRAME,
                                    final_snapshot.last_price,
                                )
                                final_future.add_done_callback(
                                    lambda done, snap=final_snapshot, candles=closed_df.copy(),
                                    start=previous_start_ist.isoformat():
                                    process_vlm_result_in_background(
                                        done, snap, candles, None, True, start
                                    )
                                )
                                logger.info("FINAL 15M NEMOTRON SCAN SUBMITTED | %s", symbol)
                            else:
                                logger.warning("Could not create final closed-candle chart for %s", symbol)

                        # Clear only runtime chart PNGs from the completed cycle.
                        # JSON reports are kept permanently.
                        delete_runtime_chart_history(symbol)
                        last_scan_time.pop(candle_key, None)

                    active_candle_start[candle_key] = current_candle_start

                    # Current-cycle chart: overwrites charts/<SYMBOL>.png and archives PNG.
                    image_b64 = generate_chart_base64(symbol, all_df)
                    if not image_b64:
                        logger.warning("Chart generation returned no image for %s", symbol)
                        continue
                    save_chart_image(symbol, image_b64, current_candle_start)
                    logger.info("LIVE 15M CHART UPDATED | %s", symbol)

                    # Regular in-cycle Nemotron scan, once every 60 seconds per symbol.
                    now = time.monotonic()
                    with scan_lock:
                        last_scan = last_scan_time.get(candle_key, 0.0)
                        already_running = candle_key in scans_in_flight
                        should_submit = (now - last_scan >= SCAN_INTERVAL_SECONDS) and not already_running
                        if should_submit:
                            scans_in_flight.add(candle_key)
                    if not should_submit:
                        continue

                    try:
                        future = executor.submit(
                            analyze_pre_generated_chart,
                            symbol,
                            image_b64,
                            TIMEFRAME,
                            snapshot.last_price,
                        )
                        with scan_lock:
                            last_scan_time[candle_key] = time.monotonic()
                        cycle_start = datetime.fromtimestamp(
                            current_candle_start / 1000, tz=timezone.utc
                        ).astimezone(IST).isoformat()
                        future.add_done_callback(
                            lambda done, snap=snapshot, candles=all_df.copy(), key=candle_key,
                            start=cycle_start: process_vlm_result_in_background(
                                done, snap, candles, key, False, start
                            )
                        )
                        logger.info("NEMOTRON SCAN SUBMITTED | %s | every %ss", symbol, SCAN_INTERVAL_SECONDS)
                    except Exception:
                        with scan_lock:
                            scans_in_flight.discard(candle_key)
                        logger.exception("Could not submit Nemotron scan for %s", symbol)

                except Exception:
                    logger.exception("Market monitoring failed for %s", symbol)


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------

def monitor_markets() -> None:
    clear_old_charts()
    logger.info(
        "Starting CryptoGuardian Pattern Scanner | "
        "Chart interval: %ss | Nemotron interval: %ss | Timeframe: %s | Timezone: IST",
        CHART_UPDATE_INTERVAL_SECONDS,
        SCAN_INTERVAL_SECONDS,
        TIMEFRAME,
    )

    exchanges = create_exchange()
    try:
        load_exchange_markets(exchanges)
        watchlist = load_watchlist()

        if not watchlist:
            logger.error("Watchlist is empty. Scanner will stop.")
            return

        while True:
            loop_started = time.monotonic()
            fast_loop(exchanges, watchlist)

            elapsed = time.monotonic() - loop_started
            sleep_seconds = max(
                0.0,
                CHART_UPDATE_INTERVAL_SECONDS - elapsed,
            )
            time.sleep(sleep_seconds)

    except KeyboardInterrupt:
        logger.info("Market monitoring stopped by user.")

    finally:
        logger.info("Shutting down background workers...")
        executor.shutdown(wait=True, cancel_futures=False)

        for exchange in exchanges.values():
            try:
                exchange.close()
            except Exception:
                logger.exception("Error while closing exchange")


if __name__ == "__main__":
    monitor_markets()
