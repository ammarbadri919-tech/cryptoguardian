
import logging
import runpy
from pathlib import Path

# CryptoGuardian Pattern Decision Agent

PROJECT_ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger("PatternDecisionAgent")


def run():
    logger.info("Starting CryptoGuardian Pattern Decision Agent")
    logger.info("Connecting to Market Monitor, Nemotron and Gemini...")

    monitor_path = PROJECT_ROOT / "tools" / "market_monitor.py"

    if not monitor_path.exists():
        logger.error("market_monitor.py not found: %s", monitor_path)
        return

    try:
        runpy.run_path(str(monitor_path), run_name="__main__")

    except KeyboardInterrupt:
        logger.info("Pattern Decision Agent stopped by user.")

    except Exception:
        logger.exception("Pattern Decision Agent encountered an error.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    run()
