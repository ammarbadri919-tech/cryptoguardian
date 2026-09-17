"""
CryptoGuardian - Central Configuration
All project paths, settings, and constants.
"""
from pathlib import Path

# Project root (this file lives in configs/, so parent.parent = project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
FEATURES_DIR = DATA_DIR / "features"

# Models / results / logs
MODELS_DIR = PROJECT_ROOT / "models"
RESULTS_DIR = PROJECT_ROOT / "results"
LOGS_DIR = PROJECT_ROOT / "logs"

# Ensure directories exist
for d in [DATA_DIR, RAW_DATA_DIR, PROCESSED_DATA_DIR, FEATURES_DIR,
          MODELS_DIR, RESULTS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Dataset configuration
TIMEFRAME = "15m"
YEARS_OF_DATA = 3
LOOKBACK_WINDOW = 672

# Coins
COINS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "DOT/USDT", "LINK/USDT",
    "LTC/USDT", "TRX/USDT", "ATOM/USDT", "UNI/USDT", "NEAR/USDT",
    "APT/USDT", "ARB/USDT", "OP/USDT", "FIL/USDT", "ETC/USDT",
]

# Output files
RAW_DATA_FILE = RAW_DATA_DIR / "crypto_20coins_3year_15m.parquet"
FEATURE_DATA_FILE = FEATURES_DIR / "crypto_20coins_features_15m.parquet"

# Training
TEST_SIZE = 0.2
VAL_SIZE = 0.1
RANDOM_SEED = 42

# Transformer
TRANSFORMER = {
    "d_model": 128,
    "n_heads": 8,
    "n_layers": 4,
    "dropout": 0.1,
    "seq_len": LOOKBACK_WINDOW,
}