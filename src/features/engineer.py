import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from configs import config


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def compute_atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def add_features(df):
    df = df.sort_values("date").copy()

    df["return_1h"] = df["close"].pct_change(4)
    df["return_4h"] = df["close"].pct_change(16)

    df["rsi_14"] = compute_rsi(df["close"], 14)






    ema_12 = df["close"].ewm(span=12, adjust=False).mean()
    ema_26 = df["close"].ewm(span=26, adjust=False).mean()
    macd = ema_12 - ema_26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    df["macd_hist"] = macd - macd_signal

    df["atr_14"] = compute_atr(df, 14)

    df["volume_ratio"] = df["volume"] / df["volume"].rolling(96).mean()

    df["hour"] = df["date"].dt.hour
    df["day_of_week"] = df["date"].dt.dayofweek

    df["close_1h"] = df["close"].rolling(4).mean()
    df["high_1h"] =  df["high"].rolling(4).max()
    df["low_1h"] = df["low"].rolling(4).min()
    df["volume_1h"] = df["volume"].rolling(4).sum()
    df["return_1h_avg"] = df["return_1h"].rolling(4).mean()




    df["target_1h"] = df["close"].shift(-4) / df["close"] - 1
    df["target_2h"] = df["close"].shift(-8) / df["close"] - 1
    df["target_3h"] = df["close"].shift(-12) / df["close"] - 1
    df["target_4h"] = df["close"].shift(-16) / df["close"] - 1

    return df


def main():
    print("Loading raw data...")
    df = pd.read_parquet(config.RAW_DATA_FILE)
    print(f"Loaded {len(df):,} rows, {df['symbol'].nunique()} coins")

    all_features = []
    for symbol in df["symbol"].unique():
        coin_df = df[df["symbol"] == symbol].copy()
        coin_df = add_features(coin_df)
        all_features.append(coin_df)
        print(f"  {symbol}")

    features_df = pd.concat(all_features, ignore_index=True)

    features_df = features_df.sort_values(["symbol", "date"]).reset_index(drop=True)
    features_df["time_idx"] = features_df.groupby("symbol").cumcount()
    features_df["group_id"] = features_df["symbol"]

    before = len(features_df)
    features_df = features_df.replace([np.inf, -np.inf], np.nan)
    features_df = features_df.dropna().reset_index(drop=True)
    print(f"\nDropped {before - len(features_df):,} rows")

    print(f"Final shape: {features_df.shape}")
    print(f"Columns ({len(features_df.columns)}):")
    for c in features_df.columns:
        print(f"  - {c}")

    config.FEATURE_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    features_df.to_parquet(config.FEATURE_DATA_FILE, index=False)
    print(f"\nSaved: {config.FEATURE_DATA_FILE}")


if __name__ == "__main__":
    main()