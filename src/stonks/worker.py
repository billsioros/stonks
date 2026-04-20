"""Background worker to fetch and cache stock data daily."""

import logging
import time
import schedule

from stonks.universe import UniverseLoader
from stonks.metrics import MetricsProvider
from stonks.cache import LocalCache
from stonks.config import FINNHUB_API_KEY, DATA_DIR

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(DATA_DIR / "worker.log")],
)
logger = logging.getLogger("stonks.worker")


def job():
    """Main data fetching job."""
    logger.info("Starting daily data fetch job...")

    if not FINNHUB_API_KEY:
        logger.error("FINNHUB_API_KEY not set. Cannot run worker.")
        return

    try:
        cache = LocalCache()
        loader = UniverseLoader(api_key=FINNHUB_API_KEY, cache=cache)
        provider = MetricsProvider(api_key=FINNHUB_API_KEY, cache=cache)

        # 1. Fetch symbols
        logger.info("Fetching US symbols...")
        symbols_df = loader.get_common_stocks(exchange="US")
        if symbols_df.empty:
            logger.warning("No symbols found.")
            return

        # Limit symbols for free tier safety, but worker can be more patient
        # We'll fetch top 500 symbols
        symbol_list = symbols_df["symbol"].sort_values().head(500).tolist()
        total = len(symbol_list)
        logger.info(f"Preparing to fetch metrics for {total} symbols...")

        # 2. Fetch basic metrics (one by one, rate limited by MetricsProvider)
        for i, sym in enumerate(symbol_list):
            logger.info(f"[{i + 1}/{total}] Fetching metrics for {sym}...")
            provider.fetch_metrics_raw(sym)

            # Additional safety sleep for worker (1s between base calls)
            # This ensures we stay well within 60/min
            time.sleep(1.1)

        # 3. Enrichment (only for very high quality ones to save time)
        # We'll skip candle enrichment in background worker to avoid excessive calls
        # Unless specifically requested. For now, basic financials are enough.

        logger.info("Daily data fetch job completed successfully.")

    except Exception as e:
        logger.exception(f"Error during worker job: {e}")


def run_worker():
    """Run the worker loop."""
    logger.info("Stonks Background Worker started.")

    # Run once at startup
    job()

    # Schedule daily at 00:00
    schedule.every().day.at("00:00").do(job)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    run_worker()
