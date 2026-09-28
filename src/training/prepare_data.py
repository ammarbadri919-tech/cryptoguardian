import sys
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from configs import config


def main():
    print(f"Loading raw data... {config.FEATURE_DATA_FILE}")
    df = pd.read_parquet(config.FEATURE_DATA_FILE)
    print(f"loaded {len(df)} rows {len(df['symbol'].unique())} unique symbols")

    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

    print("Created sampling of 5000 rows per coin")
    sample_dfs = []
    for symbol in df["symbol"].unique():
        coin_df = df[df["symbol"] == symbol].copy()
        coin_sample = coin_df.iloc[:5000].copy()
        coin_sample["time_idx"] = range(len(coin_sample))
        sample_dfs.append(coin_sample)

    sample_df = pd.concat(sample_dfs, ignore_index=True)
    print(f"Samples shape: {sample_df.shape}")

    print("sample info")
    print(f"rows: {len(sample_df)}")
    print(f"Coins: {sample_df['symbol'].nunique()}")
    print(f"columns: {sample_df.columns.tolist()}")

    sample_path = Path(config.FEATURES_DIR) / "sample_15m.parquet"
    sample_df.to_parquet(sample_path, index=False)
    print(f"Saved: {sample_path}")
  


if __name__ == "__main__":
    main()