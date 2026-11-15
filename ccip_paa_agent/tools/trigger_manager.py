
import time
import logging
import math

logger = logging.getLogger("CryptoGuardian.TriggerManager")

COOLDOWN_MINUTES = 30
STRENGTH_INCREASE_THRESHOLD = 1.25
COOLDOWN_SECONDS = COOLDOWN_MINUTES * 60

last_trigger_data = {}


def safe_float(value, default=0.0):
    try:
        number = float(value)

        if not math.isfinite(number):
            return default

        return number

    except (TypeError, ValueError):
        return default


def calculate_strength(anomaly_event: dict) -> float:

    signals = anomaly_event.get("signals", {})
    scores = []

    if signals.get("rsi_extreme"):
        rsi = safe_float(anomaly_event.get("rsi"), 50)

        if rsi >= 70 or rsi <= 30:
            scores.append(abs(rsi - 50) / 20)

    if signals.get("volume_spike"):
        volume_ratio = safe_float(anomaly_event.get("volume_ratio"))

        if volume_ratio > 0:
            scores.append(volume_ratio / 3)

    if signals.get("price_jump"):
        price_change = abs(
            safe_float(anomaly_event.get("price_change_pct"))
        )
        scores.append(price_change / 1.0)

    if signals.get("high_volatility"):
        volatility = safe_float(
            anomaly_event.get("volatility_pct")
        )
        scores.append(volatility / 2.0)

    if not scores:
        return 0.0

    return sum(scores) / len(scores)


def should_forward_to_vlm(anomaly_event: dict) -> bool:

    if not isinstance(anomaly_event, dict) or not anomaly_event:
        logger.warning("Invalid or empty anomaly event.")
        return False

    exchange = anomaly_event.get("exchange")
    symbol = anomaly_event.get("symbol")
    signals = anomaly_event.get("signals")

    if not exchange or not symbol or not isinstance(signals, dict):
        logger.warning("Missing exchange, symbol, or invalid signals.")
        return False

    current_signals = {
        name for name, active in signals.items()
        if active is True
    }

    if not current_signals:
        return False

    trigger_key = f"{exchange}_{symbol}"
    now = time.monotonic()
    current_strength = calculate_strength(anomaly_event)

    previous = last_trigger_data.get(trigger_key)

    if previous is None:

        reason = "First anomaly detected"

    else:

        elapsed = now - previous["time"]

        if elapsed >= COOLDOWN_SECONDS:

            reason = "30-minute cooldown expired"

        else:

            previous_signals = previous["signals"]
            new_signals = current_signals - previous_signals

            if new_signals:

                reason = f"New signals detected: {new_signals}"

            elif (
                previous["strength"] > 0
                and current_strength >=
                previous["strength"] * STRENGTH_INCREASE_THRESHOLD
            ):

                reason = "Anomaly strength increased by 25% or more"

            else:

                logger.info(
                    f"{trigger_key}: Repeated anomaly ignored. "
                    f"Cooldown: {elapsed / 60:.1f}/"
                    f"{COOLDOWN_MINUTES} minutes."
                )
                return False

    last_trigger_data[trigger_key] = {
        "time": now,
        "signals": current_signals,
        "strength": current_strength
    }

    logger.warning(
        f"FORWARDING TO VLM | Exchange: {exchange} | "
        f"Symbol: {symbol} | Reason: {reason} | "
        f"Strength: {current_strength:.2f}"
    )

    return True
