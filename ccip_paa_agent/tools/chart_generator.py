
import base64
import logging
from pathlib import Path

import mplfinance as mpf
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

logger = logging.getLogger("cryptoguardian.chart_generator")

BASE_DIR = Path(__file__).resolve().parent.parent
CHART_DIR = BASE_DIR / "charts"

CHART_DIR.mkdir(parents=True, exist_ok=True)


def clear_old_charts():
    """Delete existing PNG charts when a new monitoring session starts."""
    try:
        for image_path in CHART_DIR.glob("*.png"):
            image_path.unlink()
            logger.info("OLD CHART DELETED | %s", image_path.name)

        logger.info("Old chart cleanup completed.")

    except Exception:
        logger.exception("Failed to clear old charts.")


def generate_chart_base64(
    symbol: str,
    chart_df: pd.DataFrame
) -> str | None:
    """
    Generate the latest candlestick chart.
    Overwrites the existing PNG and returns Base64 for Nemotron.
    Displays timestamps in Indian Standard Time.
    """

    required = [
        "timestamp", "open", "high",
        "low", "close", "volume"
    ]

    if chart_df is None or chart_df.empty:
        logger.warning("No chart data available for %s", symbol)
        return None

    if not all(column in chart_df.columns for column in required):
        logger.error("Missing chart columns for %s", symbol)
        return None

    fig = None

    try:
        chart_data = chart_df.tail(100).copy()

        for column in ["open", "high", "low", "close", "volume"]:
            chart_data[column] = pd.to_numeric(
                chart_data[column],
                errors="coerce"
            )

        chart_data["timestamp"] = (
            pd.to_datetime(
                chart_data["timestamp"],
                unit="ms",
                utc=True,
                errors="coerce"
            )
            .dt.tz_convert("Asia/Kolkata")
            .dt.tz_localize(None)
        )

        chart_data.dropna(subset=required, inplace=True)

        if chart_data.empty:
            logger.warning("No valid chart candles for %s", symbol)
            return None

        chart_data.rename(columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume"
        }, inplace=True)

        chart_data.set_index("timestamp", inplace=True)
        chart_data.sort_index(inplace=True)

        latest = chart_data.iloc[-1]

        logger.info(
            "LIVE CHART | %s | Time IST: %s | "
            "Open: %.10f | High: %.10f | Low: %.10f | "
            "Close: %.10f | Volume: %.4f",
            symbol,
            chart_data.index[-1].strftime("%Y-%m-%d %H:%M:%S"),
            latest["Open"],
            latest["High"],
            latest["Low"],
            latest["Close"],
            latest["Volume"]
        )

        style = mpf.make_mpf_style(
            base_mpf_style="yahoo",
            facecolor="#131722",
            edgecolor="#131722",
            figcolor="#131722",
            gridcolor="#2a2e39",
            gridstyle="-",
            rc={
                "axes.labelcolor": "white",
                "axes.titlecolor": "white",
                "xtick.color": "white",
                "ytick.color": "white",
                "font.size": 10
            }
        )

        safe_symbol = symbol.replace("/", "_").replace(":", "_")
        image_path = CHART_DIR / f"{safe_symbol}.png"

        fig, axes = mpf.plot(
            chart_data,
            type="candle",
            style=style,
            title={
                "title": f"{symbol} | IST",
                "color": "white",
                "size": 16
            },
            volume=True,
            figsize=(12, 6),
            datetime_format="%H:%M",
            xrotation=30,
            returnfig=True
        )

        # Display small prices as full decimals instead of scientific notation.
        price_axis = axes[0]

        price_axis.yaxis.set_major_formatter(
            mticker.FuncFormatter(
                lambda value, position: (
                    f"{value:.12f}".rstrip("0").rstrip(".")
                )
            )
        )

        fig.savefig(
            image_path,
            dpi=150,
            bbox_inches="tight",
            facecolor=fig.get_facecolor()
        )

        plt.close(fig)
        fig = None

        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(
                image_file.read()
            ).decode("utf-8")

        logger.info(
            "CHART SAVED | %s | %s",
            symbol,
            image_path
        )

        return base64_image

    except Exception:
        if fig is not None:
            plt.close(fig)

        logger.exception(
            "Chart generation failed for %s",
            symbol
        )
        return None
