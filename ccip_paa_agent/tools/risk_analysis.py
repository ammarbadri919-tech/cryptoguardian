"""
CryptoGuardian — Risk Analysis Engine
File: tools/risk_analysis.py
"""

from __future__ import annotations
from typing import Any, Optional, Sequence
import numpy as np
import pandas as pd

DEFAULT_TARGETS = (1.0, 2.0, -1.0, -2.0)

def candles_to_dataframe(candles: Any) -> pd.DataFrame:
    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    
    if isinstance(candles, pd.DataFrame):
        df = candles.copy()
        
        # FIX 1: If Kronos returns a DatetimeIndex, we explicitly convert it to Unix milliseconds
        # instead of letting pd.to_numeric() destroy the dates.
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            df = df.rename(columns={df.columns[0]: "timestamp"})
            df["timestamp"] = df["timestamp"].astype("int64") // 1_000_000
            
        df.columns = [str(c).lower() for c in df.columns]
        
        if "timestamp" not in df.columns:
            if "timestamp_ms" in df.columns: df["timestamp"] = df["timestamp_ms"]
            elif "time" in df.columns: df["timestamp"] = df["time"]
            
        missing = set(columns) - set(df.columns)
        if missing: raise ValueError(f"Missing candle columns: {sorted(missing)}")
        df = df[columns].copy()
    else:
        df = pd.DataFrame(candles, columns=columns)
        
    for col in columns: 
        df[col] = pd.to_numeric(df[col], errors="coerce")
        
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"]).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    
    if df.empty: raise ValueError("No valid candles supplied.")
    if (df[["open", "high", "low", "close"]] <= 0).any().any(): raise ValueError("Candle prices must be positive.")
       # FIX 1.5: Normalize candle boundaries to prevent Kronos hallucinations
    df = df.copy()
    
    # Preserve original Kronos predictions for diagnostics
    df["raw_high"] = df["high"]
    df["raw_low"] = df["low"]

    # Normalize candle boundaries
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)

    # Validate normalized candles
    invalid = (
        (df["high"] < df["low"])
        | (df["low"] <= 0)
        | (df["open"] <= 0)
        | (df["close"] <= 0)
    )

    if invalid.any():
        raise ValueError("Kronos produced invalid OHLC predictions.")
   ## if (df["high"] < df["low"]).any(): raise ValueError("Invalid candle: high is below low.")
    
    return df

def calculate_wilders_rsi(close: pd.Series, period: int = 14) -> float:
    # FIX 2: Check if we have enough history
    if len(close) < period + 1:
        raise ValueError(f"Need at least {period + 1} candles to calculate RSI, got {len(close)}.")

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.rolling(window=period).mean().iloc[period]
    avg_loss = loss.rolling(window=period).mean().iloc[period]
    
    # FIX 2: Handle edge case where both average gains and losses are zero
    if avg_gain == 0 and avg_loss == 0:
        return 50.0
        
    for i in range(period + 1, len(close)):
        avg_gain = (avg_gain * (period - 1) + gain.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss.iloc[i]) / period
        
    if avg_loss == 0:
        return 100.0
        
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))

def analyze_risk(historical_candles: Any, forecast_candles: Optional[Any] = None, candle_minutes: int = 5, forecast_minutes: int = 30, targets_pct: Sequence[float] = DEFAULT_TARGETS) -> dict[str, Any]:
    history = candles_to_dataframe(historical_candles)
    latest_timestamp = history["timestamp"].iloc[-1]
    window_ms = 24 * 60 * 60 * 1000
    history_24h = history[history["timestamp"] >= latest_timestamp - window_ms].copy()
    current_price = float(history_24h["close"].iloc[-1])
    
    # FIX 3: Properly calculate and label volatility
    returns = np.log(history_24h["close"]).diff().dropna()
    vol_per_candle = float(returns.std(ddof=1)) if len(returns) >= 2 else None
    
    # Horizon volatility based on the forecast minutes
    horizon_vol = None
    if vol_per_candle is not None:
        horizon_vol = vol_per_candle * np.sqrt(forecast_minutes / candle_minutes)
    
    result: dict[str, Any] = {
        "status": "historical_analysis_only", 
        "current_price": current_price, 
        "historical_volatility_per_candle_pct": vol_per_candle * 100 if vol_per_candle else None,
        "estimated_horizon_volatility_pct": horizon_vol * 100 if horizon_vol else None,
        "forecast": None, 
        "targets": {}, 
        "warnings": []
    }
    
    if forecast_candles is None:
        return result

    forecast = candles_to_dataframe(forecast_candles)
    expected_candles = int(np.ceil(forecast_minutes / candle_minutes))
    
    if len(forecast) < expected_candles:
        raise ValueError(f"Expected {expected_candles} forecast candles, received {len(forecast)}.")
        
    forecast = forecast.iloc[:expected_candles].copy()
    closes = forecast["close"].to_numpy(dtype=float)
    highs = forecast["high"].to_numpy(dtype=float)
    lows = forecast["low"].to_numpy(dtype=float)
    
    final_price = float(closes[-1])
    change_pct = (final_price / current_price - 1) * 100
    
    result["status"] = "forecast_analyzed"
    result["forecast"] = {
        "predicted_final_price": final_price, 
        "predicted_change_pct": float(change_pct)
    }
    
    for target in targets_pct:
        target = float(target)
        if target == 0: continue
        target_price = current_price * (1 + target / 100)
        
        hit_indices = np.flatnonzero(highs >= target_price) if target > 0 else np.flatnonzero(lows <= target_price)
        reached_touch = len(hit_indices) > 0
        reached_close = (closes[-1] >= target_price) if target > 0 else (closes[-1] <= target_price)
        
        result["targets"][f"{target:+g}%"] = {
            "target_price": float(target_price), 
            "reached_touch": bool(reached_touch), 
            "reached_close": bool(reached_close),
            "estimated_first_hit_minutes": (int(hit_indices[0] + 1) * candle_minutes if reached_touch else None)
        }
        
    return result

def evaluate_risk_bridge(symbol: str, historical_candles: Any, forecast_candles: Any, candle_minutes: int = 5) -> dict[str, Any]:
    try:
        history = candles_to_dataframe(historical_candles)
        latest_timestamp = history["timestamp"].iloc[-1]
        history = history[history["timestamp"] >= latest_timestamp - 86_400_000].copy()
        
        if len(history) < 50: 
            raise ValueError(f"Need at least 50 historical candles in the 24-hour window; got {len(history)}.")
            
        close = history["close"]
        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        rsi14 = calculate_wilders_rsi(close, 14)
        
        analysis = analyze_risk(historical_candles=history, forecast_candles=forecast_candles, candle_minutes=candle_minutes, forecast_minutes=30, targets_pct=(2.0,))
        
        forecast = analysis.get("forecast")
        target = analysis.get("targets", {}).get("+2%", {})
        
        if forecast is None: 
            raise ValueError("No valid model forecast was produced.")
        
        checks = {
            "ema20_above_ema50": ema20 > ema50, 
            "rsi_between_50_and_70": 50 <= rsi14 <= 70, 
            "forecast_close_reaches_plus_2_percent": bool(target.get("reached_close", False)) 
        }
        
        reasons = []
        if not checks["ema20_above_ema50"]: reasons.append("EMA 20 is not above EMA 50.")
        if not checks["rsi_between_50_and_70"]: reasons.append(f"RSI 14 is outside 50–70 (value: {rsi14:.2f}).")
        if not checks["forecast_close_reaches_plus_2_percent"]: reasons.append("Forecast final close does not reach the +2% target.")
        
        approved = all(checks.values())
        
        return {
            "symbol": symbol, 
            "verdict": "APPROVED" if approved else "REJECTED", 
            "checks": checks, 
            "indicators": {"ema20": ema20, "ema50": ema50, "rsi14": rsi14}, 
            "forecast": forecast, 
            "target_analysis": target, 
            "historical_volatility_per_candle_pct": analysis["historical_volatility_per_candle_pct"],
            "estimated_horizon_volatility_pct": analysis["estimated_horizon_volatility_pct"],
            "reasons": reasons, 
            "execution_enabled": False
        }
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return {
            "symbol": symbol, 
            "verdict": "REJECTED", 
            "checks": {}, 
            "reasons": [str(exc)], 
            "warnings": ["Risk evaluation failed; no trade execution was performed."],
            "execution_enabled": False
        }