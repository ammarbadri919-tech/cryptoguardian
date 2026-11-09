from __future__ import annotations
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ccxt
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent.parent
WATCHLIST_FILE = BASE_DIR / "selected_coins.csv"

TIMEFRAME = "1m"
OHLCV_LIMIT = 30
FAST_LOOP_INTERVAL_SECONDS = 3

EXCHANGE_NAMES = ("binance", "kraken", "bybit")
QUOTE_CURRENCIES = ("USDT", "USD")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cryptoguardian.market_monitor")


@dataclass
class MarketSnapshot:
    exchange: str
    symbol: str
    timeframe: str
    fetched_at: str
    last_price: float| None
    candle_timestamp: int| None
    open: float| None
    high: float| None
    low: float| None
    close: float| None
    volume: float| None
    candle_is_probably_closed: bool

def create_exchange() -> dict[str, Any]:
    exchange_classes = {
        "binance": ccxt.binance,
        "kraken": ccxt.kraken,
        "bybit": ccxt.bybit,
    }
    clients ={}

    for name, exchange_class in exchange_classes.items():
        clients[name]= exchange_class({
            "enableRateLimit": True,
            "timeout": 20000,
            "options": {"defaultType": "spot"},
        })

    return clients
def load_exchange_markets(exchanges: dict[str, Any]) -> None:
    for name, exchange in exchanges.items():
        try:
            exchange.load_markets()
            logger.info("%s: loaded %d markets", name, len(exchange.markets))
        except (ccxt.NetworkError, ccxt.ExchangeError) as exc:
            logger.error("%s: could not load markets: %s", name, exc)

def load_watchlist(filepath: Path = WATCHLIST_FILE) -> list[str]:
    if not filepath.exists():
        logger.warning("Watchlist file %s does not exist. Using empty watchlist.", filepath)
        return []

    try:
        df = pd.read_csv(filepath)
        if "symbol" not in df.columns:
            logger.error("Watchlist file %s does not contain 'symbol' column.", filepath)
            return []

        
        bases=[]
        for value in df["symbol"].dropna().astype(str):
            item = value.strip().upper()
            if not item:
                continue
            base = item.split("/")[0] .strip()
            if base and base not in bases:
                bases.append(base)
        return bases
    except Exception as exc:
        logger.exception("CCould not REd Watchinglist file %s",exc)
        return []
def supported_pairs(exchange: Any, base: str) -> list[str]:
    pairs = []
    for quote in QUOTE_CURRENCIES:
        symbol = f"{base}/{quote}"
        market = exchange.markets.get(symbol)
        if market and market.get("active", True) and market.get("spot", True):
            pairs.append(symbol)
    return pairs
def _to_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
def fetch_market_snapshot(exchange_name: str, exchange: Any, symbol: str) -> tuple[MarketSnapshot | None, pd.DataFrame | None]:
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=OHLCV_LIMIT)
        if not candles:
            return None, None
        ticker = exchange.fetch_ticker(symbol)
        last_price = _to_float(ticker.get("last"))
        columns = ["timestamp", "open", "high", "low", "close", "volume"]
        df = pd.DataFrame(candles, columns=columns)
        latest = df.iloc[-1]

        candle_ms = int(latest["timestamp"])
      ##  candle_time = datetime.fromtimestamp(candle_ms / 1000, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        candle_closed = (now.timestamp() * 1000) >= (candle_ms + 60_000)

        snapshot = MarketSnapshot(
            exchange=exchange_name,
            symbol=symbol,
            timeframe=TIMEFRAME,
            fetched_at=now.isoformat(timespec="seconds"),
            last_price=last_price,
            candle_timestamp=candle_ms,
            open=_to_float(latest["open"]),
            high=_to_float(latest["high"]),
            low=_to_float(latest["low"]),
            close=_to_float(latest["close"]),
            volume=_to_float(latest["volume"]),
            candle_is_probably_closed=candle_closed,)
        return snapshot ,df
    except ccxt.BadSymbol:
        logger.debug("%s: symbol %s not found", exchange_name, symbol)
    except Exception as exc:
        logger.error("%s: error fetching data for %s: %s", exchange_name, symbol, exc)
    return None , None


def print_snapshot(snapshot: MarketSnapshot) -> None:
    """Print one compact market-data row."""
    price = f"{snapshot.last_price:,.4f}" if snapshot.last_price is not None else "n/a"
    volume = f"{snapshot.volume:,.2f}" if snapshot.volume is not None else "n/a"
    status = "CLOSED" if snapshot.candle_is_probably_closed else "FORMING"
    
    print(
        f"{snapshot.exchange.upper():7} | {snapshot.symbol:12} | "
        f"Price={price:>10} | Vol={volume:>12} | {status}"
    )
last_prices: dict[tuple[str, str], float] = {}


def fast_loop(
    exchanges: dict[str, Any],
    watchlist: list[str]
) -> None:

    for base in watchlist:
        for exchange_name, exchange in exchanges.items():

            if not exchange.markets:
                continue

            pairs = supported_pairs(exchange, base)

            for symbol in pairs:
                try:
                    ticker = exchange.fetch_ticker(symbol)

                    current_price = _to_float(ticker.get("last"))

                    if current_price is None:
                        continue

                    price_key = (exchange_name, symbol)

                    last_prices[price_key] = current_price

                    logger.info(
                        "%s | %s | Price: %.6f",
                        exchange_name,
                        symbol,
                        current_price
                    )

                except ccxt.NetworkError:
                    logger.warning(
                        "%s network error for %s",
                        exchange_name,
                        symbol
                    )

                except ccxt.ExchangeError:
                    logger.exception(
                        "%s exchange error for %s",
                        exchange_name,
                        symbol
                    )

def monitor_markets() -> None:
    exchanges = create_exchange()

    try:
        load_exchange_markets(exchanges)

        watchlist = load_watchlist()

        if not watchlist:
            logger.warning("Watchlist is empty. Stopping monitor.")
            return

        logger.info(
            "CryptoGuardian Monitor Started: %s",
            ", ".join(watchlist)
        )

        while True:
            fast_loop(exchanges, watchlist)

            time.sleep(FAST_LOOP_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logger.info("Market monitoring stopped by user.")

    except Exception:
        logger.exception("Market monitor error")

    finally:
        for exchange in exchanges.values():
            try:
                exchange.close()
            except Exception:
                logger.exception("Error closing exchange")

if __name__ == "__main__":
    try:
        monitor_markets()
    except Exception as exc:
        logger.error("Error in main execution: %s", exc)
        



