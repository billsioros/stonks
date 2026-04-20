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

        # Fetch ALL symbols (no limit)
        symbol_list = symbols_df["symbol"].sort_values().tolist()
        total = len(symbol_list)
        logger.info(
            f"Preparing to sync metrics for {total} symbols (respecting 1-day TTL)..."
        )

        # 2. Fetch basic metrics
        # provider.fetch_metrics_raw checks internal SQLite cache with METRICS_CACHE_TTL (24h)
        # It will only hit the API if the data is missing or stale.
        fetched = 0
        for i, sym in enumerate(symbol_list):
            if i % 100 == 0 and i > 0:
                logger.info(f"Progress: {i}/{total} ({i / total:.1%})")

            # Check if cached first to avoid even rate limit wait if we don't need to hit API
            cache_key = f"metrics_{sym}"
            cached = cache.get(cache_key, ttl=86400)  # 24h

            if cached is None:
                provider.fetch_metrics_raw(sym)
                fetched += 1
                # Small optional sleep if we actually fetched,
                # but MetricsProvider handled rate limiting anyway.

        logger.info(
            f"Daily sync completed. Symbols processed: {total}. Actual API calls made: {fetched}."
        )

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
