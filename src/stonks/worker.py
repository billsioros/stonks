"""Background worker to fetch and persist stock data daily."""

import logging
import time
import schedule
from typing import Any

from stonks.universe import UniverseLoader
from stonks.metrics import MetricsProvider
from stonks.store import SQLiteStore
from stonks.config import FINNHUB_API_KEY, DATA_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(DATA_DIR / "worker.log")],
)
logger = logging.getLogger("stonks.worker")


def job():
    """Main data fetching job - fetch directly and persist."""
    logger.info("🚀 Starting daily data sync...")

    if not FINNHUB_API_KEY:
        logger.error("❌ FINNHUB_API_KEY not set. Cannot run worker.")
        return

    try:
        store = SQLiteStore()
        loader = UniverseLoader(api_key=FINNHUB_API_KEY)
        provider = MetricsProvider(api_key=FINNHUB_API_KEY)

        logger.info("📡 Loading symbol universe...")
        symbols_df = loader.get_common_stocks(exchange="US")
        if symbols_df.empty:
            logger.warning("⚠️ No symbols found.")
            return

        symbol_meta = symbols_df.set_index("symbol").to_dict("index")
        store.save_metadata("universe_size", len(symbol_meta))
        logger.info(f"📊 Syncing {len(symbol_meta)} symbols...")

        synced = 0
        for i, sym in enumerate(symbol_meta):
            if i % 100 == 0 and i > 0:
                logger.info(
                    f"Progress: {i}/{len(symbol_meta)} ({i / len(symbol_meta):.1%})"
                )

            try:
                raw = provider.fetch_metrics_raw(sym)
                if not raw or not raw.get("metric"):
                    store.update_sync_status(sym, "basic", "failed", "No data")
                    continue

                row: dict[str, Any] = dict(symbol_meta[sym])
                row.update(provider.normalize_metrics(sym, raw))

                candles = provider.fetch_candles_cached(sym, years=15)
                if candles and candles.get("s") == "ok":
                    c = candles.get("c", [])
                    if c:
                        row["price"] = c[-1]
                        for yrs in [5, 10, 15]:
                            idx = -(yrs * 252)
                            if abs(idx) < len(c):
                                row[f"return_cagr_{yrs}y_pct"] = (
                                    provider._calculate_cagr(c[idx], c[-1], yrs)
                                )

                if len(row) > 1:
                    store.save_stock(sym, row)
                    synced += 1
                    store.update_sync_status(sym, "basic", "success")

            except Exception as e:
                logger.error(f"Error syncing {sym}: {e}")
                store.update_sync_status(sym, "basic", "failed", str(e))

        logger.info(f"✅ Synced {synced}/{len(symbol_meta)} stocks to DB.")

    except Exception as e:
        logger.exception(f"💥 Critical error: {e}")


def run_worker():
    """Run the worker loop."""
    logger.info("🏁 Worker initialized.")

    job()

    schedule.every().day.at("00:00").do(job)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    run_worker()
