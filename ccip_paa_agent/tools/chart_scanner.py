import csv
import time
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import ccxt
import numpy as np
import pandas as pd
import torch

IST = ZoneInfo("Asia/Kolkata")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
KRONOS_PATH = PROJECT_ROOT / "vendor" / "Kronos"
sys.path.insert(0, str(KRONOS_PATH))

TIMEFRAMES = ["15m", "30m", "1h", "12h", "24h"]
SCAN_INTERVAL_SECONDS = 120
COIN_DELAY_SECONDS = 2
HISTORY_LIMIT = 288
MIN_HISTORY_CANDLES = 60

exchange = ccxt.kraken({"enableRateLimit": True, "timeout": 20000})

print("Loading Kronos-base model...")
from model import Kronos, KronosTokenizer, KronosPredictor

tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
model = Kronos.from_pretrained("NeoQuasar/Kronos-base")
model.eval()
predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)
print("Kronos model loaded.")


def format_price(price):
    price = float(price)
    if price >= 1000:
        return f"${price:,.2f}"
    if price >= 1:
        return f"${price:.4f}"
    if price >= 0.01:
        return f"${price:.6f}"
    return f"${price:.10f}"


def load_user_coins():
    csv_path = PROJECT_ROOT / "selected_coins.csv"
    if not csv_path.exists():
        print(f"Coin file not found: {csv_path}")
        return []

    coins = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            symbol = (row.get("symbol") or "").strip().upper()
            if symbol:
                symbol = symbol.replace("/", "").replace("USD", "")
                coins.append(f"{symbol}/USD")

    coins = list(dict.fromkeys(coins))
    print(f"Loaded {len(coins)} coins: {', '.join(coins)}")
    return coins


def fetch_with_retry(fetch_function, *args, retries=3, delay=2, **kwargs):
    for attempt in range(1, retries + 1):
        try:
            return fetch_function(*args, **kwargs)
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
            print(f"Kraken network issue ({attempt}/{retries}): {type(exc).__name__}")
            if attempt < retries:
                time.sleep(delay)
        except ccxt.BaseError as exc:
            print(f"Kraken API error: {exc}")
            return None
    print("Kraken request failed after retries.")
    return None


def get_completed_candles(symbol, timeframe, limit=288):
    timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
    rows = fetch_with_retry(
        exchange.fetch_ohlcv, symbol, timeframe=timeframe, limit=limit + 2
    )
    if not rows:
        return None

    df = pd.DataFrame(
        rows, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    now_ms = exchange.milliseconds()
    df = df[df["timestamp"] + timeframe_ms <= now_ms].copy()
    if df.empty:
        return None

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    numeric_cols = ["open", "high", "low", "close", "volume"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=numeric_cols)
    df = df.drop_duplicates(subset="timestamp")
    df = df.sort_values("timestamp")
    return df.tail(limit).reset_index(drop=True)


def calculate_change(current_price, reference_price):
    if reference_price is None or reference_price <= 0:
        return None
    return ((current_price - reference_price) / reference_price) * 100


def run_kronos_prediction(df, pred_len, freq_minutes, live_price):
    if df is None or df.empty or len(df) < MIN_HISTORY_CANDLES:
        print("Insufficient historical candles for Kronos.")
        return None
    if not np.isfinite(float(live_price)) or float(live_price) <= 0:
        print("Invalid live price.")
        return None

    recent = df.tail(500).reset_index(drop=True)
    columns = ["open", "high", "low", "close", "volume"]
    x_df = recent[columns].copy()
    x_ts = pd.to_datetime(recent["timestamp"], utc=True)
    y_ts = pd.Series(pd.date_range(
        start=x_ts.iloc[-1] + pd.Timedelta(minutes=freq_minutes),
        periods=pred_len,
        freq=f"{freq_minutes}min"
    ))

    with torch.inference_mode():
        pred_df = predictor.predict(
            df=x_df, x_timestamp=x_ts, y_timestamp=y_ts,
            pred_len=pred_len, T=1.0, top_p=0.9, sample_count=1
        )

    if not isinstance(pred_df, pd.DataFrame) or pred_df.empty:
        print("Kronos returned an empty prediction.")
        return None
    if len(pred_df) != pred_len:
        print(f"Kronos returned {len(pred_df)} rows; expected {pred_len}.")
        return None
    missing = [column for column in columns if column not in pred_df.columns]
    if missing:
        print(f"Kronos prediction is missing columns: {missing}")
        return None

    predicted_ohlcv = pred_df[columns].apply(pd.to_numeric, errors="coerce")
    # Numeric sanity only: do not enforce High/Low candle relationships.
    if not np.isfinite(predicted_ohlcv.to_numpy()).all():
        print("Kronos returned NaN or infinite OHLCV values.")
        return None

    predicted_close = float(predicted_ohlcv["close"].iloc[-1])
    if predicted_close <= 0:
        print("Kronos returned a non-positive predicted Close.")
        return None

    predicted_pct = calculate_change(predicted_close, float(live_price))
    return {
        "predicted_price": predicted_close,
        "predicted_pct": predicted_pct,
        "predicted_ohlcv": predicted_ohlcv,
        "forecast": pred_df.copy()
    }


def generate_multi_timeframe_forecasts(history_5m, history_1h, live_price):
    print("\nGENERATING MULTI-TIMEFRAME KRONOS FORECASTS")
    configurations = {
        "15m": (history_5m, 3, 5),
        "30m": (history_5m, 6, 5),
        "1h": (history_5m, 12, 5),
        "12h": (history_1h, 12, 60),
        "24h": (history_1h, 24, 60),
    }
    forecasts = {}
    for horizon, (history, pred_len, frequency) in configurations.items():
        try:
            forecasts[horizon] = run_kronos_prediction(
                history, pred_len, frequency, live_price
            )
            if forecasts[horizon] is None:
                print(f"{horizon} forecast unavailable.")
        except Exception as exc:
            print(f"{horizon} Kronos error: {type(exc).__name__}: {exc}")
            forecasts[horizon] = None
    return forecasts


def display_multi_timeframe_forecasts(forecasts, live_price):
    print("\n" + "=" * 72)
    print("                 CRYPTOGUARDIAN MARKET FORECAST")
    print("=" * 72)
    print(f"Live Price: {format_price(live_price)}")
    print("-" * 72)
    for horizon in TIMEFRAMES:
        result = forecasts.get(horizon)
        if result is None:
            print(f"{horizon:>5} | Prediction unavailable")
            continue
        price = result["predicted_price"]
        change = result["predicted_pct"]
        direction = "BULLISH" if change > 0 else "BEARISH" if change < 0 else "FLAT"
        print(
            f"{horizon:>5} | Predicted: {format_price(price):>15} "
            f"| Change: {change:+.2f}% | {direction}"
        )
    print("=" * 72)


def scan_market(coin_symbol):
    try:
        ticker = fetch_with_retry(exchange.fetch_ticker, coin_symbol)
        if not ticker:
            print(f"Skipping {coin_symbol}: ticker unavailable.")
            return
        live_price = ticker.get("last")
        if live_price is None or not np.isfinite(float(live_price)) or float(live_price) <= 0:
            print(f"Skipping {coin_symbol}: invalid live price.")
            return
        live_price = float(live_price)

        candles_1m = fetch_with_retry(
            exchange.fetch_ohlcv, coin_symbol, timeframe="1m", limit=10
        )
        candles_5m = fetch_with_retry(
            exchange.fetch_ohlcv, coin_symbol, timeframe="5m", limit=13
        )
        if not candles_1m or len(candles_1m) < 6:
            print(f"Skipping {coin_symbol}: insufficient 1m market data.")
            return
        if not candles_5m or len(candles_5m) < 13:
            print(f"Skipping {coin_symbol}: insufficient 5m market data.")
            return

        change_5m = calculate_change(live_price, candles_1m[-6][4])
        change_1h = calculate_change(live_price, candles_5m[0][4])
        change_24h = ticker.get("percentage")

        print("\n" + "=" * 72)
        print(f"MARKET DATA: {coin_symbol}")
        print("=" * 72)
        print(f"Live Price : {format_price(live_price)}")
        print(f"5m Change  : {change_5m:+.2f}%" if change_5m is not None else "5m Change: unavailable")
        print(f"1h Change  : {change_1h:+.2f}%" if change_1h is not None else "1h Change: unavailable")
        print(
            f"24h Change : {float(change_24h):+.2f}%"
            if change_24h is not None else "24h Change: unavailable"
        )

        history_5m = get_completed_candles(coin_symbol, "5m", HISTORY_LIMIT)
        history_1h = get_completed_candles(coin_symbol, "1h", HISTORY_LIMIT)
        if (history_5m is None or history_1h is None
                or len(history_5m) < MIN_HISTORY_CANDLES
                or len(history_1h) < MIN_HISTORY_CANDLES):
            print(f"Skipping forecasts for {coin_symbol}: insufficient historical OHLCV.")
            return

        forecasts = generate_multi_timeframe_forecasts(
            history_5m, history_1h, live_price
        )
        display_multi_timeframe_forecasts(forecasts, live_price)

    except Exception as exc:
        print(f"Market scan failed for {coin_symbol}: {type(exc).__name__}: {exc}")


def main():
    try:
        exchange.load_markets()
        print("Kraken connected successfully.")
        coins = load_user_coins()
        if not coins:
            print("No coins configured in selected_coins.csv. Exiting.")
            return

        print("\nCRYPTOGUARDIAN MARKET SCANNER STARTED")
        print(f"Started at: {datetime.now(IST).strftime('%d-%m-%Y %I:%M:%S %p')} IST")
        print(f"Coins: {', '.join(coins)}")

        while True:
            cycle_start = time.monotonic()
            for coin in coins:
                if coin not in exchange.markets:
                    print(f"Skipping unsupported Kraken pair: {coin}")
                    continue
                scan_market(coin)
                time.sleep(COIN_DELAY_SECONDS)

            elapsed = time.monotonic() - cycle_start
            sleep_for = max(0, SCAN_INTERVAL_SECONDS - elapsed)
            print(f"\nSleeping {sleep_for:.0f} seconds before next scan cycle...")
            time.sleep(sleep_for)

    except KeyboardInterrupt:
        print("\nCryptoGuardian Market Scanner stopped.")
    except Exception as exc:
        print(f"Scanner startup error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
