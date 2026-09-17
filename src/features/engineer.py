"""
CryptoGuardian - Feature Engineering (15-min data)
Turns raw OHLCV into TFT-ready features.
"""
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
    return 100 - (100 / (1 + rs))


def compute_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def add_features(df):
    """Add engineered features for one coin (15-min data)."""
    df = df.sort_values('date').copy()

    # Returns (in 15-min candles)
    df['return_1h'] = df['close'].pct_change(4)       # 4 candles = 1h
    df['return_4h'] = df['close'].pct_change(16)      # 16 candles = 4h
    df['return_24h'] = df['close'].pct_change(96)     # 96 candles = 24h

    # Moving averages
    df['sma_20'] = df['close'].rolling(80).mean()     # 20 hours
    df['sma_50'] = df['close'].rolling(200).mean()    # 50 hours
    df['ema_12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema_26'] = df['close'].ewm(span=26, adjust=False).mean()

    # RSI
    df['rsi_14'] = compute_rsi(df['close'], 14)

    # MACD
    df['macd'] = df['ema_12'] - df['ema_26']
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']

    # ATR
    df['atr_14'] = compute_atr(df, 14)

    # Volatility
    df['volatility_24h'] = df['return_1h'].rolling(96).std()
    df['volatility_7d'] = df['return_1h'].rolling(672).std()

    # Volume
    df['volume_change'] = df['volume'].pct_change(1)
    df['volume_sma_24'] = df['volume'].rolling(96).mean()
    df['volume_ratio'] = df['volume'] / df['volume_sma_24']

    # Price position
    df['high_low_range'] = (df['high'] - df['low']) / df['close']
    df['close_position'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-9)

    # Time features (cyclical)
    df['hour'] = df['date'].dt.hour
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
    df['day_of_week'] = df['date'].dt.dayofweek
    df['day_sin'] = np.sin(2 * np.pi * df['day_of_week'] / 7)
    df['day_cos'] = np.cos(2 * np.pi * df['day_of_week'] / 7)

    return df


def main():
    print(f"Loading: {config.RAW_DATA_FILE}")
    df = pd.read_parquet(config.RAW_DATA_FILE)
    print(f"Loaded {len(df):,} rows, {df['symbol'].nunique()} coins")

    all_features = []
    for symbol in df['symbol'].unique():
        print(f"Processing {symbol}...")
        coin_df = df[df['symbol'] == symbol].copy()
        coin_df = add_features(coin_df)
        all_features.append(coin_df)

    features_df = pd.concat(all_features, ignore_index=True)

    before = len(features_df)
    features_df = features_df.dropna().reset_index(drop=True)
    print(f"\nDropped {before - len(features_df):,} warmup rows")

    # TFT formatting
    features_df = features_df.sort_values(['symbol', 'date']).reset_index(drop=True)
    features_df['time_idx'] = features_df.groupby('symbol').cumcount()
    features_df['group_id'] = features_df['symbol']

    print(f"Final shape: {features_df.shape}")

    config.FEATURE_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    features_df.to_parquet(config.FEATURE_DATA_FILE, index=False)

    print(f"\n✅ Saved: {config.FEATURE_DATA_FILE}")
    print(f"\nColumns ({len(features_df.columns)}):")
    for c in features_df.columns:
        print(f"  - {c}")


if __name__ == '__main__':
    main()