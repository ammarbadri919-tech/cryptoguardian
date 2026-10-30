import sys
import csv
from pathlib import Path
import ccxt
import pandas as pd
import torch
import time
from datetime import datetime, timedelta
PROJECT_ROOT = Path(__file__).resolve().parent.parent
KRONOS_PATH = PROJECT_ROOT / "vendor" / "Kronos"
sys.path.insert(0, str(KRONOS_PATH))
from tools.risk_analysis import evaluate_risk_bridge
from model import Kronos, KronosTokenizer, KronosPredictor

print("Loading Kronos-base Model (This takes a few seconds)...")
tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
model = Kronos.from_pretrained("NeoQuasar/Kronos-base")
model.eval()
predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)
exchange = ccxt.bybit({"enableRateLimit": True})


last_alert_times = {}
ALERT_COOLDOWN_MINUTES = 15
def format_price(price):
    price = float(price)

    if price >= 1000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:.4f}"
    elif price >= 0.01:
        return f"${price:.6f}"
    else:
        return f"${price:.10f}"




def load_user_coins():
    csv_path = PROJECT_ROOT / "selected_coins.csv"
    if not csv_path.exists():
        print(f"File not found at {csv_path}; using default coins")
        return []
    coins = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row.get("symbol", "").strip().upper()
            if symbol:
                symbol = symbol.replace("/", "").replace("USDT", "")
                coins.append(f"{symbol}/USDT")
               ## coins.append(f"{symbol}")
    print(f"Loaded {len(coins)} coins from user file...")
    return coins

def scan_sudden_changes(coin_symbol, threshold=4.0):
    try:
        ohlcv_1m = exchange.fetch_ohlcv(coin_symbol, timeframe="1m", limit=10)
        if not ohlcv_1m:
            print(f"No candle data returned for {coin_symbol}")
            return
        ticker = exchange.fetch_ticker(coin_symbol)
        live_price = ticker.get("last")
        if live_price is None or live_price <= 0:
            print(f"Invalid live price for {coin_symbol}")
            return

        target_ms = exchange.milliseconds() - 5 * 60 * 1000
        reference_candle = min(
            ohlcv_1m,
            key=lambda candle: abs((candle[0] + 60_000) - target_ms),
        )
        price_5m_ago = reference_candle[4]
        if price_5m_ago is None or price_5m_ago <= 0:
            print(f"Invalid reference price for {coin_symbol}")
            return

        sudden_change = ((live_price - price_5m_ago) / price_5m_ago) * 100
        fmt = ".2f" if live_price > 1 else ".8f"

     ##   print(f"Reference (5m): ${price_5m_ago:,.4f} | Live: ${live_price:,.8f} | Change: {sudden_change:+.2f}%")
        print(
        f"Reference (5m): {format_price(price_5m_ago)} | "
        f"Live: {format_price(live_price)} | "
        f"Change: {sudden_change:+.2f}%")

        if abs(sudden_change) < threshold:
            print("No alert: movement is below the threshold")
            return

        now = datetime.now()
        if coin_symbol in last_alert_times:
            elapsed = now - last_alert_times[coin_symbol]
            if elapsed < timedelta(minutes=ALERT_COOLDOWN_MINUTES):
                print(f"Cooldown active for {coin_symbol}")
                return

        last_alert_times[coin_symbol] = now
        direction = "PUMP" if sudden_change > 0 else "DUMP"
        print("\n" + "=" * 20)
        print(f"ALERT: Sudden {threshold}%+ move detected for {coin_symbol}!")
        print(f"Move: {sudden_change:+.2f}% ({direction})")
        print("Feeding 24-hour context to Kronos for prediction...")

        ohlcv_5m = exchange.fetch_ohlcv(coin_symbol, timeframe="5m", limit=288)
        if not ohlcv_5m:
            print(f"No 5-minute candle data returned for {coin_symbol}")
            return
        df = pd.DataFrame(ohlcv_5m, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.iloc[:-1].reset_index(drop=True)
        if df.empty:
            print(f"Not enough candle data for {coin_symbol}")
            return

        pred_len = 6
        recent = df.tail(287).reset_index(drop=True)
        x_df = recent[["open", "high", "low", "close", "volume"]].copy()
        x_timestamp = recent["timestamp"].copy()
        last_time = x_timestamp.iloc[-1]
        y_timestamp = pd.Series(pd.date_range(start=last_time + pd.Timedelta(minutes=5), periods=pred_len, freq="5min"))

        with torch.inference_mode():
            pred_df = predictor.predict(
                df=x_df,
                x_timestamp=x_timestamp,
                y_timestamp=y_timestamp,
                pred_len=pred_len,
                T=1.0,
                top_p=0.9,
                sample_count=1,
            )
        predicted_price = pred_df["close"].iloc[-1]
        predicted_pct = ((predicted_price - live_price) / live_price) * 100
        print(f"Kronos Prediction (Next 30 min): ${predicted_price:{fmt}} ({predicted_pct:+.2f}%)")
        risk_report = evaluate_risk_bridge(
            symbol=coin_symbol,
            historical_candles=df,
            forecast_candles = pred_df,
            candle_minutes=5

        )

        print("\n" + "=" * 50)
        print(f" FINAL RISK VERDICT: {risk_report['verdict']}")
        if risk_report['verdict'] == "APPROVED":
            print(f" RSI: {risk_report['indicators']['rsi14']:.2f} | EMA20: ${risk_report['indicators']['ema20']:,.2f} | EMA50: ${risk_report['indicators']['ema50']:,.2f}")
        else:
            print(f" Reasons: {risk_report['reasons']}")
        print("=" * 50 + "\n")
       ## print("=" * 20 + "\n")

    except Exception as e:
        print(f"Error scanning {coin_symbol}: {e}")
if __name__=="__main__":
    coins =load_user_coins()
    print("LIVE SCANNER STARTED ")
    while True:
        print(f"\n" + "="*50)
        print(f" Waking up at {datetime.now().strftime('%H:%M:%S')}")
        print("="*50)
        
        for coin in coins:
            scan_sudden_changes(coin, threshold=0.01)
            
        print("\n💤 Sleeping for 2 minutes before the next check...")
        time.sleep(120) 











