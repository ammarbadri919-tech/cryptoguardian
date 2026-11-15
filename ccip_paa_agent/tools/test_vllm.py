
import pandas as pd
import numpy as np
import mplfinance as mpf

# Generate sample crypto data
np.random.seed(42)

dates = pd.date_range(
    start="2026-11-12 10:00",
    periods=100,
    freq="1min"
)

close = 100 + np.cumsum(np.random.randn(100))

data = pd.DataFrame({
    "Open": close + np.random.randn(100) * 0.5,
    "High": close + abs(np.random.randn(100)),
    "Low": close - abs(np.random.randn(100)),
    "Close": close,
    "Volume": np.random.randint(100, 1000, 100)
}, index=dates)

# Generate chart
mpf.plot(
    data,
    type="candle",
    volume=True,
    style="charles",
    title="CryptoGuardian - BTC/USDT",
    savefig="test_chart.png"
)

print("Chart generated successfully!")
