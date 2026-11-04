import sys
import csv
import time
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta, timezone
import ccxt
import pandas as pd
import torch
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
def get_current_time():
    return datetime.now(IST).strftime("%d-%m-%Y %I:%M:%S %p")


IST = ZoneInfo("Asia/Kolkata")
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
exchange = ccxt.kraken({"enableRateLimit": True,"timeout": 15000})


try:
    exchange.load_markets()
    print("Kraken connected successfully!")

    print("BTC/USD available:", "BTC/USD" in exchange.markets)

    candles = exchange.fetch_ohlcv(
        "BTC/USD",
        timeframe="1m",
        limit=5
    )

    print("Candles received:", len(candles))
    print("Latest candle:", candles[-1])

except Exception as e:
    print(f"Kraken error: {type(e).__name__}: {e}")





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
                symbol = symbol.replace("/", "").replace("USD", "")
                coins.append(f"{symbol}/USD")
               ## coins.append(f"{symbol}")
    print(f"Loaded {len(coins)} coins from user file...")
    return coins
def get_completed_candles(symbol, timeframe, limit):
    timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit + 2)
    if not ohlcv: return None
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    now_ms = exchange.milliseconds()
    df = df[df["timestamp"]+timeframe_ms <=now_ms].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    numeric_cols = ["open", "high", "low", "close", "volume"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    return df.dropna().drop_duplicates(subset="timestamp").sort_values("timestamp")


def validate_prediction(pred_df, expected_length):
    if not isinstance(pred_df, pd.DataFrame) or pred_df.empty or len(pred_df) != expected_length: return False
    required = ["open", "high", "low", "close", "volume"]
    if not all(col in pred_df.columns for col in required): return False
    
    prices = pred_df[required].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(prices.to_numpy()).all(): return False
    
    ohlc = prices[["open", "high", "low", "close"]]
    if (ohlc <= 0).any().any(): return False
    if (prices["volume"] < 0).any(): return False
    if (prices["high"] < prices["low"]).any(): return False
    if (prices["high"] < ohlc[["open", "close"]].max(axis=1)).any(): return False
    if (prices["low"] > ohlc[["open", "close"]].min(axis=1)).any(): return False
    return True
def run_kronos_prediction(df, pred_len, freq_minutes, live_price):
  

    if df is None or df.empty :
        return None, None , None
    live_price = float(live_price)
    if not np.isfinite(live_price) or live_price <= 0:
        return None, None , None
    recent = df.tail(500).reset_index(drop=True)
    x_df = recent[["open", "high", "low", "close", "volume"]].copy()
    x_ts = pd.to_datetime(recent["timestamp"], utc=True)
    y_ts = pd.Series(pd.date_range(start=x_ts.iloc[-1] + pd.Timedelta(minutes=freq_minutes), periods=pred_len, freq=f"{freq_minutes}min"))
    with torch.inference_mode():
        pred_df = predictor.predict(
            df =x_df,
            x_timestamp =x_ts,
            y_timestamp =y_ts,
            pred_len =pred_len,
            T =1.0,
            top_p =0.9,
            sample_count =1
        )
    pred_df = pred_df.copy()
    if "timestamp" not in pred_df.columns:
     pred_df.insert(
        0,
        "timestamp",
        pd.to_datetime(y_ts).to_numpy()
    )

    if not validate_prediction(pred_df, pred_len):
        return None, None , None
    predicted_price = pred_df["close"].iloc[-1] # <--- ADD THIS LINE

    predicted_pct = ((predicted_price - live_price) / live_price) * 100
    if predicted_pct < -25.0 or predicted_pct > 50.0:
      return None, None, None
    return predicted_price, predicted_pct, pred_df
def generate_multi_timeframe_forecasts(history_5m, history_1h, live_price):
    print("\nGENERATING MULTI-TIMEFRAME KRONOS FORECASTS")
    forecasts = {}
    forecasts["15m"] = run_kronos_prediction(history_5m, 3, 5, live_price) 
    forecasts["30m"] = run_kronos_prediction(history_5m, 6, 5, live_price)
    forecasts["1h"] = run_kronos_prediction(history_5m, 12, 5, live_price)
    forecasts["12h"] = run_kronos_prediction(history_1h, 12, 60, live_price)
    forecasts["24h"] = run_kronos_prediction(history_1h, 24, 60, live_price)
    
    invalid = [
    h for h, res in forecasts.items()
    if any(v is None for v in res)

]
    if invalid:
        print(f" Invalid forecast(s): {', '.join(invalid)}. Skipping coin.")
        return None
        
    return forecasts

def display_multi_timeframe_forecasts(forecasts):
    print("\n" + "=" * 65)
    print("       CRYPTOGUARDIAN FUTURE PRICE FORECAST")
    print("=" * 65)
    directions = []
    
    for horizon in ["15m", "30m", "1h", "12h", "24h"]:
        if forecasts.get(horizon) is None or forecasts[horizon][0] is None:
            print(f"{horizon:>5} | Prediction failed.")
            continue

            
        predicted_price, predicted_pct, _ = forecasts[horizon] 


            
        
        direction = "BULLISH" if predicted_pct > 0 else "BEARISH" if predicted_pct < 0 else "FLAT"
        directions.append(direction)
        print(f"{horizon:>5} | Predicted: {format_price(predicted_price):>15} | Change: {predicted_pct:+.2f}% | {direction}")
        
    if all(d == "BULLISH" for d in directions): market_view = "BULLISH AGREEMENT"
    elif all(d == "BEARISH" for d in directions): market_view = "BEARISH AGREEMENT"
    elif len(set(directions)) > 1: market_view = "MIXED TIMEFRAME SIGNALS"
    else: market_view = "FLAT / UNCERTAIN"

    if not directions:
        market_view = "NO PREDICTIONS AVAILABLE"
    elif all(d == "BULLISH" for d in directions): 
        market_view = "BULLISH AGREEMENT"
    elif all(d == "BEARISH" for d in directions): 
        market_view = "BEARISH AGREEMENT"
    elif len(set(directions)) > 1: 
        market_view = "MIXED TIMEFRAME SIGNALS"
    else: 
        market_view = "FLAT / UNCERTAIN"
    
    print("-" * 65)
    print(f"OVERALL VIEW: {market_view}")
    return market_view



def prepare_risk_frame(df):
    risk_df = df.copy()
    risk_df["timestamp"] = (pd.to_datetime(risk_df["timestamp"], utc=True).astype("int64") // 1_000_000)
    return risk_df


def scan_sudden_changes(coin_symbol, threshold=0.01):
    """
    Main cryptocurrency scanner.

    Responsibilities:
    1. Fetch live market price.
    2. Detect sudden price movements.
    3. Calculate 5m, 1h and 24h changes.
    4. Apply alert cooldown.
    5. Fetch completed historical candles.
    6. Generate multi-timeframe forecasts.
    7. Send 30m forecast to Risk Agent.
    8. Display final risk verdict.
    """

    try:
       
        # ==========================================
        # STEP 2: FETCH LIVE MARKET PRICE
        # ==========================================

        ticker = exchange.fetch_ticker(coin_symbol)

        live_price = ticker.get("last")

        if not live_price:
            return

        # ==========================================
        # STEP 3: FETCH LAST 10 ONE-MINUTE CANDLES
        # ==========================================

        ohlcv_1m = exchange.fetch_ohlcv(
            coin_symbol,
            timeframe="1m",
            limit=10
        )

        # ==========================================
        # STEP 4: CALCULATE TARGET TIME (5 MIN AGO)
        # ==========================================

        target_ms = exchange.milliseconds() - 5 * 60 * 1000

        # Find candle whose closing time is closest
        # to approximately five minutes ago.

        ref_candle = min(
            ohlcv_1m,
            key=lambda c: abs((c[0] + 60_000) - target_ms)
        )

        # ==========================================
        # STEP 5: EXTRACT 5-MINUTE REFERENCE PRICE
        # ==========================================

        price_5m_ago = ref_candle[4]

        # ==========================================
        # STEP 6: CALCULATE 5-MINUTE PRICE CHANGE
        # ==========================================

        sudden_change = (
            (live_price - price_5m_ago)
            / price_5m_ago
        ) * 100

        # ==========================================
        # STEP 7: FETCH HISTORICAL 5-MINUTE CANDLES
        # ==========================================

        ohlcv_1h_hist = exchange.fetch_ohlcv(
            coin_symbol,
            timeframe="5m",
            limit=13
        )

        # ==========================================
        # STEP 8: CALCULATE APPROXIMATE 1-HOUR CHANGE
        # ==========================================

        change_1h = (
            (live_price - ohlcv_1h_hist[0][4])
            / ohlcv_1h_hist[0][4]
        ) * 100

        # ==========================================
        # STEP 9: GET 24-HOUR PRICE CHANGE
        # ==========================================

        change_24h = ticker.get("percentage", 0.0)

        # ==========================================
        # STEP 10: DISPLAY LIVE MARKET INFORMATION
        # ==========================================

        print(
            f"\n📊 {coin_symbol} | "
            f"Live: {format_price(live_price)}"
        )

        print(
            f"5m: {sudden_change:+.2f}% | "
            f"1h: {change_1h:+.2f}% | "
            f"24h: {change_24h:+.2f}%"
        )

        # ==========================================
        # STEP 11: CHECK SUDDEN MOVEMENT THRESHOLD
        # ==========================================

        if abs(sudden_change) < threshold:
            return

        # ==========================================
        # STEP 12: GET CURRENT UTC TIME
        # ==========================================

        now = datetime.now(timezone.utc)

        # ==========================================
        # STEP 13: CHECK ALERT COOLDOWN
        # ==========================================

        if (
            coin_symbol in last_alert_times
            and now - last_alert_times[coin_symbol]
            < timedelta(minutes=ALERT_COOLDOWN_MINUTES)
        ):

            print(
                f"   └─ Cooldown active for {coin_symbol}"
            )

            return

        # ==========================================
        # STEP 14: FETCH COMPLETED HISTORICAL CANDLES
        # ==========================================

        history_5m = get_completed_candles(
            coin_symbol,
            "5m",
            288
        )

        history_1h = get_completed_candles(
            coin_symbol,
            "1h",
            288
        )

        # ==========================================
        # STEP 15: VALIDATE HISTORICAL DATA
        # ==========================================

        if (
            history_5m is None
            or history_1h is None
            or len(history_5m) < 60
            or len(history_1h) < 60
        ):

            print(
                "[WARNING] Insufficient historical candles."
            )

            return

        # ==========================================
        # STEP 16: GENERATE MULTI-TIMEFRAME FORECASTS
        # ==========================================

        forecasts = generate_multi_timeframe_forecasts(
            history_5m,
            history_1h,
            live_price
        )

        if forecasts is None:
            return
        display_multi_timeframe_forecasts(forecasts)

        if forecasts.get("30m") is None or forecasts["30m"][0] is None:
              print("   └─ Skipping Risk Agent: 30m prediction failed.")
              print("-" * 65)
              return
        last_alert_times[coin_symbol] = now
        pred30 = forecasts["30m"][2]
        risk_history = prepare_risk_frame(history_5m)
        risk_forecast = prepare_risk_frame(pred30)


        # ==========================================
        # STEP 17: DISPLAY FORECAST RESULTS
        # ==========================================

        ##

        # ==========================================
        # STEP 18: RECORD LAST ALERT TIME
        # ==========================================

        last_alert_times[coin_symbol] = now

        # ==========================================
        # STEP 19: EXTRACT 30-MINUTE FORECAST
        # ==========================================

        pred30 = forecasts["30m"][2]

        # ==========================================
        # STEP 20: PREPARE HISTORICAL RISK DATA
        # ==========================================

        risk_history = prepare_risk_frame(history_5m)

        # ==========================================
        # STEP 21: PREPARE FORECAST RISK DATA
        # ==========================================

        risk_forecast = prepare_risk_frame(pred30)

        # ==========================================
        # STEP 22: SEND DATA TO RISK AGENT
        # ==========================================

        risk_report = evaluate_risk_bridge(
            symbol=coin_symbol,
            historical_candles=risk_history,
            forecast_candles=risk_forecast,
            candle_minutes=5,
        )

        # ==========================================
        # STEP 23: DISPLAY FINAL RISK VERDICT
        # ==========================================

        print(
            f"\n🛡️ RISK VERDICT: "
            f"{risk_report.get('verdict', 'UNKNOWN')}"
        )

        # ==========================================
        # STEP 24: HANDLE APPROVED FORECAST
        # ==========================================

        if risk_report.get("verdict") == "APPROVED":

            ema20_val = format_price(
                risk_report["indicators"]["ema20"]
            )

            ema50_val = format_price(
                risk_report["indicators"]["ema50"]
            )

            print(
                f"   └─ RSI: "
                f"{risk_report['indicators']['rsi14']:.2f} "
                f"| EMA20: {ema20_val} "
                f"| EMA50: {ema50_val}"
            )

        # ==========================================
        # STEP 25: HANDLE REJECTED / OTHER VERDICTS
        # ==========================================

        else:

            reasons = risk_report.get("reasons") or []

            if reasons:

                print(
                    f"   └─ Risk reason: {reasons[0]}"
                )

        # ==========================================
        # STEP 26: PRINT SEPARATOR
        # ==========================================

        print("-" * 65)

    # ==============================================
    # STEP 27: HANDLE UNEXPECTED ERRORS
    # ==============================================

    except Exception as e:

        print(
            f"Skipping {coin_symbol}: {e}"
        )
if __name__ == "__main__":
    coins = load_user_coins()
    start_time = datetime.now(IST)

    print("\nCRYPTOGUARDIAN MULTI-TIMEFRAME SCANNER STARTED")
    print(f"STARTED AT: {start_time.strftime('%I:%M:%S %p')}")
    print(f"DATE: {start_time.strftime('%d-%m-%Y')}")
    print("TIMEZONE: IST")
    
    while True:
        cycle_start = time.monotonic()

        for coin in coins:
            scan_sudden_changes(coin, threshold=0.01)
            time.sleep(2)

        elapsed = time.monotonic() - cycle_start
        sleep_for = max(0, 120 - elapsed)
        print(f"\n💤 Sleeping {sleep_for:.0f} seconds before next scan cycle...")
        time.sleep(sleep_for)

