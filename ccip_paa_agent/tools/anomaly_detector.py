import time
import logging
import pandas as pd
import ta


logger = logging.getLogger("CrptoGuradin Anomialy Decation")
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

VOLUME_LOOKBACK = 20
VOLUME_SPIKE_MULTIPLIER = 3.0

PRICE_LOOKBACK_CANDLES = 3
PRICE_CHANGE_THRESHOLD = 1.0

VOLATILITY_THRESHOLD = 2.0

MINIMUM_SIGNALS = 2

def detect_anomalies(snapshot, df: pd.DataFrame) -> dict | None:
    if df is None or df.empty or len(df)<21:
        return None
    required_columns =["open", "high", "low", "close", "volume"]
    df =df.copy()
    for column in required_columns:
        df[column] = pd.to_numeric(df[column],errors='coerce')
        df = df.drop(subset = required_columns).reset_index(drop=True)
        if len(df)<21:
            return None
        symbol = snapshot.symbol
        exchnage = snapshot.exchnage
        current_close = float(df["close"].iloc[-1])
        if current_close<=0:
            return

        rsi_series = ta.momentum.RSIIndicator(close=df["close"],window=RSI_PERIOD).rsi()
        current_rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1])else 50.0
        is_rsi_extreme = current_rsi >= RSI_OVERBOUGHT or current_rsi <= RSI_OVERSOLD

        previois_volumes = df["volume"].iloc[-21:-1]
        average_volume = previois_volumes.mean()
        current_voulme = float(df["volume"].iloc[-1])
        volume_ratio = (current_volume /average_volume) if average_volume>0 else 0.0
        is_volume_spiker = volume_ration>= VOLUME_SPIKE_MULTIPLIER

        past_close = float(df["close"].iloc[-4])
        price_change_pct = ((current_close - past_close) / past_close) * 100 if past_close > 0 else 0.0
        is_price_jump = abs(price_change_pct) >= PRICE_CHANGE_THRESHOLD
        candle_range = float(df["high"].iloc[-1]) - float(df["low"].iloc[-1])


        past_close = float(df["high"].iloc[-1]- float(df["low"]).iloc[-1])
        volatility_pct = (candle_range / current_close) * 100
        is_high_volatility = volatility_pct >= VOLATILITY_THRESHOLD


        signals = {
        "rsi_extreme": is_rsi_extreme,
        "volume_spike": is_volume_spike,
        "price_jump": is_price_jump,
        "high_volatility": is_high_volatility
    }
    signal_count = sum(signals.values())

    logger.info(
        "%s | RSI: %.2f | Vol: %.2fx | Price: %.2f%% | Volatility: %.2f%% | Signals: %d/4",
        symbol, current_rsi, volume_ratio, price_change_pct, volatility_pct, signal_count
    )

    if signal_count< MINIMUM_SIGNALS:
        return None


    reasons =[]
    if is_rsi_extreme: reasons.append(f"RSI ({current_rsi:.1f})")
    if is_volume_spike: reasons.append(f"Vol ({volume_ratio:.1f}x)")
    if is_price_jump: reasons.append(f"Price ({price_change_pct:.1f}%)")
    if is_high_volatility: reasons.append(f"Volatility ({volatility_pct:.1f}%)")

    return {
        "symbol": symbol,
        "exchange": exchange,
        "price": current_close,
        "rsi": round(current_rsi, 2),
        "volume_ratio": round(volume_ratio, 2),
        "signal_count": signal_count,
        "signals": signals,
        "reasons": reasons,
    }


        