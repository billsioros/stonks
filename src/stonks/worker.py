"""Background worker to fetch and persist stock data on a recurring interval."""

import logging
import time

import schedule

from stonks.config import DATA_DIR, WORKER_INTERVAL_MINUTES
from stonks.hedgefollow import apply_flags, fetch_largest_buys
from stonks.stockanalysis import current_discount_rate, fetch_rows
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
        discount_rate = current_discount_rate()
        logger.info("📉 DCF discount rate: %.0f%%", discount_rate * 100)
        rows = fetch_rows(discount_rate=discount_rate)
        if not rows:
            logger.warning("⚠️ No screener data found.")
            return

        largest_buys = fetch_largest_buys()
        if largest_buys is None:
            logger.warning("⚠️ HedgeFollow buys unavailable; flag left unknown")
        else:
            matched = apply_flags(rows, largest_buys)
            logger.info(
                "🐋 %s symbols in HedgeFollow's largest %s buys",
                matched,
                len(largest_buys),
            )

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
