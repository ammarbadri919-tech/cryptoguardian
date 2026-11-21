
import logging
import runpy
from pathlib import Path


# CryptoGuardian Market Scanner Agent

PROJECT_ROOT = Path(__file__).resolve().parents[2]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("MarketScannerAgent")


def run():
    logger.info("Starting CryptoGuardian Market Scanner Agent")
    logger.info("Connecting to existing chart scanner...")

    scanner_path = PROJECT_ROOT / "tools" / "chart_scanner.py"

    if not scanner_path.exists():
        logger.error("chart_scanner.py not found: %s", scanner_path)
        return

    try:
        runpy.run_path(str(scanner_path), run_name="__main__")
    except KeyboardInterrupt:
        logger.info("Market Scanner Agent stopped by user.")
    except Exception:
        logger.exception("Market Scanner Agent encountered an error.")


if __name__ == "__main__":
    run()
