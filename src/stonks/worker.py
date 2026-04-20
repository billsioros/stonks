"""Background worker to fetch and cache stock data daily."""

import logging
import time
import schedule
from typing import List

from stonks.universe import UniverseLoader
from stonks.metrics import MetricsProvider
from stonks.cache import LocalCache
from stonks.store import SQLiteStore
from stonks.config import FINNHUB_API_KEY, DATA_DIR

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(DATA_DIR / "worker.log")],
)
logger = logging.getLogger("stonks.worker")


def sync_symbols_phase(
    symbols: List[str],
    provider: MetricsProvider,
    store: SQLiteStore,
    cache: LocalCache,
    sync_type: str,
) -> int:
    """Sync a specific type of data for a list of symbols."""
    total = len(symbols)
    fetched = 0

    for i, sym in enumerate(symbols):
        if i % 100 == 0 and i > 0:
            logger.info(f"[{sync_type}] Progress: {i}/{total} ({i / total:.1%})")

        try:
            if sync_type == "basic":
                # Check cache first
                cache_key = f"metrics_{sym}"
                cached = cache.get(cache_key, ttl=86400)  # 24h
                if cached is None:
                    res = provider.fetch_metrics_raw(sym)
                    if res and res.get("metric"):
                        store.update_sync_status(sym, sync_type, "success")
                        fetched += 1
                    else:
                        store.update_sync_status(
                            sym, sync_type, "failed", "Empty response"
                        )
                else:
                    store.update_sync_status(sym, sync_type, "success")

            elif sync_type == "candles":
                # Check cache first (15y candles)
                cache_key = f"candles_{sym}_15y"
                cached = cache.get(
                    cache_key, ttl=86400 * 7
                )  # 1 week for candles is enough
                if cached is None:
                    res = provider.fetch_candles_cached(sym, years=15)
                    if res and res.get("s") == "ok":
                        store.update_sync_status(sym, sync_type, "success")
                        fetched += 1
                    else:
                        err = res.get("s", "unknown error") if res else "No response"
                        store.update_sync_status(sym, sync_type, "failed", err)
                else:
                    store.update_sync_status(sym, sync_type, "success")

        except Exception as e:
            logger.error(f"Error syncing {sym} ({sync_type}): {e}")
            store.update_sync_status(sym, sync_type, "failed", str(e))

    return fetched


def job():
    """Main data fetching job."""
    logger.info("🚀 Starting comprehensive daily data sync...")

    if not FINNHUB_API_KEY:
        logger.error("❌ FINNHUB_API_KEY not set. Cannot run worker.")
        return

    try:
        cache = LocalCache()
        store = SQLiteStore()
        loader = UniverseLoader(api_key=FINNHUB_API_KEY, cache=cache)
        provider = MetricsProvider(api_key=FINNHUB_API_KEY, cache=cache)

        # 1. Fetch US symbols
        logger.info("📡 Fetching US symbols universe...")
        symbols_df = loader.get_common_stocks(exchange="US")
        if symbols_df.empty:
            logger.warning("⚠️ No symbols found.")
            return

        all_symbols = symbols_df["symbol"].sort_values().tolist()
        store.save_metadata("universe_size", len(all_symbols))

        # 2. Sync Basic Metrics
        logger.info(
            f"📊 Phase 1: Syncing basic financials for {len(all_symbols)} symbols..."
        )
        sync_symbols_phase(all_symbols, provider, store, cache, "basic")

        # 3. Sync Candles (Historical CAGRs)
        logger.info(
            f"🕯️ Phase 2: Syncing historical candles for {len(all_symbols)} symbols..."
        )
        sync_symbols_phase(all_symbols, provider, store, cache, "candles")

        # 4. Retry Failed
        for stype in ["basic", "candles"]:
            failed = store.get_failed_symbols(stype)
            if failed:
                logger.info(f"🔄 Retrying {len(failed)} failed symbols for {stype}...")
                sync_symbols_phase(failed, provider, store, cache, stype)

        stats = store.get_last_sync_info()
        logger.info(f"✅ Sync complete! Stats: {stats}")

    except Exception as e:
        logger.exception(f"💥 Critical error during worker job: {e}")


def run_worker():
    """Run the worker loop."""
    logger.info("🏁 Stonks Background Worker initialized.")

    # Run once at startup
    job()

    # Schedule daily at 00:00
    schedule.every().day.at("00:00").do(job)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    run_worker()
