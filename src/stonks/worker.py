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


def job() -> None:
    """Main data fetching job with strict prioritization and blocking."""
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
        universe_size = len(symbol_meta)
        all_symbols_set = set(symbol_meta.keys())
        store.save_metadata("universe_size", universe_size)

        synced_basic = set(store.get_synced_symbols("basic"))
        stale_basic = set(store.get_stale_symbols("basic", stale_hours=24))
        synced_candles = set(store.get_synced_symbols("candles"))
        stale_candles = set(store.get_stale_symbols("candles", stale_hours=24))

        logger.info(
            f"📊 Universe: {universe_size} symbols | Basic: {len(synced_basic)} synced, {len(stale_basic)} stale | Candles: {len(synced_candles)} synced, {len(stale_candles)} stale"
        )

        processed_symbols = set()

        # Phase 1: Missing Basic (highest priority)
        # Symbols with no basic data → fetch basic + candles
        missing_basic = [sym for sym in all_symbols_set if sym not in synced_basic]
        if missing_basic:
            logger.info(
                f"📊 Phase 1: Syncing {len(missing_basic)} symbols with missing basic data..."
            )
            count = 0
            for i, sym in enumerate(missing_basic):
                if i % 100 == 0 and i > 0:
                    logger.info(
                        f"Progress: {i}/{len(missing_basic)} ({i / len(missing_basic):.1%})"
                    )

                try:
                    raw = provider.fetch_metrics_raw(sym)
                    if not raw or not raw.get("metric"):
                        store.update_sync_status(sym, "basic", "failed", "No data")
                        continue

                    row: dict[str, Any] = dict(symbol_meta[sym])
                    row.update(provider.normalize_metrics(sym, raw))
                    store.save_stock(sym, row)
                    store.update_sync_status(sym, "basic", "success")

                    # Immediately fetch candles for this symbol
                    candles = provider.fetch_candles_cached(sym, years=15)
                    if candles and candles.get("s") == "ok":
                        c = candles.get("c", [])
                        if c:
                            row = {"symbol": sym, "price": c[-1]}
                            for yrs in [5, 10, 15]:
                                idx = -(yrs * 252)
                                if abs(idx) < len(c):
                                    row[f"return_cagr_{yrs}y_pct"] = (
                                        provider._calculate_cagr(c[idx], c[-1], yrs)
                                    )
                            store.save_stock(sym, row)
                            store.update_sync_status(sym, "candles", "success")

                    processed_symbols.add(sym)
                    count += 1

                except Exception as e:
                    logger.error(f"Error syncing {sym}: {e}")
                    store.update_sync_status(sym, "basic", "failed", str(e))

            logger.info(f"✅ Phase 1 complete: {count}/{len(missing_basic)} symbols.")
        else:
            logger.info("✅ Phase 1: No missing basic data.")

        # Phase 2: Missing Candles (blocked by Phase 1)
        # Symbols with basic but no candles
        missing_candles = [
            sym
            for sym in all_symbols_set
            if sym in synced_basic
            and sym not in synced_candles
            and sym not in processed_symbols
        ]
        if missing_candles:
            logger.info(
                f"📊 Phase 2: Syncing {len(missing_candles)} symbols with missing candles..."
            )
            count = 0
            for i, sym in enumerate(missing_candles):
                if i % 100 == 0 and i > 0:
                    logger.info(
                        f"Progress: {i}/{len(missing_candles)} ({i / len(missing_candles):.1%})"
                    )

                try:
                    candles = provider.fetch_candles_cached(sym, years=15)
                    if candles and candles.get("s") == "ok":
                        c = candles.get("c", [])
                        if c:
                            row = {"symbol": sym, "price": c[-1]}
                            for yrs in [5, 10, 15]:
                                idx = -(yrs * 252)
                                if abs(idx) < len(c):
                                    row[f"return_cagr_{yrs}y_pct"] = (
                                        provider._calculate_cagr(c[idx], c[-1], yrs)
                                    )
                            store.save_stock(sym, row)
                            store.update_sync_status(sym, "candles", "success")
                            processed_symbols.add(sym)
                            count += 1
                    else:
                        store.update_sync_status(sym, "candles", "failed", "No candles")
                except Exception as e:
                    logger.error(f"Error syncing candles {sym}: {e}")
                    store.update_sync_status(sym, "candles", "failed", str(e))

            logger.info(f"✅ Phase 2 complete: {count}/{len(missing_candles)} symbols.")
        else:
            logger.info("✅ Phase 2: No missing candles.")

        # Phase 3: Stale Basic (blocked by Phases 1 and 2)
        stale_basic_syms = [sym for sym in stale_basic if sym not in processed_symbols]
        if stale_basic_syms:
            logger.info(
                f"📊 Phase 3: Re-syncing {len(stale_basic_syms)} symbols with stale basic data..."
            )
            count = 0
            for i, sym in enumerate(stale_basic_syms):
                if i % 100 == 0 and i > 0:
                    logger.info(
                        f"Progress: {i}/{len(stale_basic_syms)} ({i / len(stale_basic_syms):.1%})"
                    )

                try:
                    raw = provider.fetch_metrics_raw(sym)
                    if not raw or not raw.get("metric"):
                        store.update_sync_status(sym, "basic", "failed", "No data")
                        continue

                    row: dict[str, Any] = dict(symbol_meta[sym])
                    row.update(provider.normalize_metrics(sym, raw))
                    store.save_stock(sym, row)
                    store.update_sync_status(sym, "basic", "success")

                    # Fetch candles (might also be stale)
                    candles = provider.fetch_candles_cached(sym, years=15)
                    if candles and candles.get("s") == "ok":
                        c = candles.get("c", [])
                        if c:
                            row = {"symbol": sym, "price": c[-1]}
                            for yrs in [5, 10, 15]:
                                idx = -(yrs * 252)
                                if abs(idx) < len(c):
                                    row[f"return_cagr_{yrs}y_pct"] = (
                                        provider._calculate_cagr(c[idx], c[-1], yrs)
                                    )
                            store.save_stock(sym, row)
                            store.update_sync_status(sym, "candles", "success")

                    processed_symbols.add(sym)
                    count += 1

                except Exception as e:
                    logger.error(f"Error syncing {sym}: {e}")
                    store.update_sync_status(sym, "basic", "failed", str(e))

            logger.info(
                f"✅ Phase 3 complete: {count}/{len(stale_basic_syms)} symbols."
            )
        else:
            logger.info("✅ Phase 3: No stale basic data.")

        # Phase 4: Stale Candles (blocked by Phases 1, 2, and 3)
        stale_candles_syms = [
            sym for sym in stale_candles if sym not in processed_symbols
        ]
        if stale_candles_syms:
            logger.info(
                f"📊 Phase 4: Re-syncing {len(stale_candles_syms)} symbols with stale candles..."
            )
            count = 0
            for i, sym in enumerate(stale_candles_syms):
                if i % 100 == 0 and i > 0:
                    logger.info(
                        f"Progress: {i}/{len(stale_candles_syms)} ({i / len(stale_candles_syms):.1%})"
                    )

                try:
                    candles = provider.fetch_candles_cached(sym, years=15)
                    if candles and candles.get("s") == "ok":
                        c = candles.get("c", [])
                        if c:
                            row = {"symbol": sym, "price": c[-1]}
                            for yrs in [5, 10, 15]:
                                idx = -(yrs * 252)
                                if abs(idx) < len(c):
                                    row[f"return_cagr_{yrs}y_pct"] = (
                                        provider._calculate_cagr(c[idx], c[-1], yrs)
                                    )
                            store.save_stock(sym, row)
                            store.update_sync_status(sym, "candles", "success")
                            processed_symbols.add(sym)
                            count += 1
                    else:
                        store.update_sync_status(sym, "candles", "failed", "No candles")
                except Exception as e:
                    logger.error(f"Error syncing candles {sym}: {e}")
                    store.update_sync_status(sym, "candles", "failed", str(e))

            logger.info(
                f"✅ Phase 4 complete: {count}/{len(stale_candles_syms)} symbols."
            )
        else:
            logger.info("✅ Phase 4: No stale candles.")

    except Exception as e:
        logger.exception(f"💥 Critical error: {e}")


def run_worker() -> None:
    """Run the worker loop."""
    logger.info("🏁 Worker initialized.")

    job()

    schedule.every().day.at("00:00").do(job)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    run_worker()
