"""Background worker to fetch and persist stock data on a recurring interval."""

import logging
import time

import schedule

from stonks.config import DATA_DIR, WORKER_INTERVAL_MINUTES
from stonks.stockanalysis import fetch_rows
from stonks.store import SQLiteStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(DATA_DIR / "worker.log")],
)
logger = logging.getLogger("stonks.worker")


def job() -> None:
    """Sync the full StockAnalysis screener dataset into the local store."""
    logger.info("🚀 Starting data sync...")
    try:
        rows = fetch_rows()
        if not rows:
            logger.warning("⚠️ No screener data found.")
            return

        store = SQLiteStore()
        store.replace_stocks(rows)
        store.save_metadata("universe_size", len(rows))

        logger.info("✅ Synced %s symbols", len(rows))
    except Exception:
        logger.exception("💥 Critical error")


def run_worker() -> None:
    """Run the worker loop."""
    logger.info("🏁 Worker initialized.")

    job()

    schedule.every(WORKER_INTERVAL_MINUTES).minutes.do(job)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    run_worker()
