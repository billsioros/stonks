"""Background worker to fetch and persist stock data daily."""

import logging
import time

import schedule

from stonks.config import DATA_DIR, YAHOO_ENRICHMENT_TTL_DAYS
from stonks.store import SQLiteStore
from stonks.yahoo import enrich_rows, preset_candidate_rows, required_preset_columns

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(DATA_DIR / "worker.log")],
)
logger = logging.getLogger("stonks.worker")


def job() -> None:
    """Sync Yahoo screener quotes and enriched fundamentals into the local store."""
    logger.info("🚀 Starting daily data sync...")
    try:
        store = SQLiteStore()
        rows = preset_candidate_rows()
        if not rows:
            logger.warning("⚠️ No screener candidates found.")
            return
        store.save_metadata("universe_size", len(rows))
        logger.info("📡 Yahoo screener returned %s candidate symbols", len(rows))

        all_symbols = {row["symbol"] for row in rows}
        synced = set(store.get_synced_symbols("fundamentals"))
        stale = set(
            store.get_stale_symbols(
                "fundamentals", stale_hours=YAHOO_ENRICHMENT_TTL_DAYS * 24
            )
        )
        targets = (all_symbols - synced) | (stale & all_symbols)
        target_rows = [row for row in rows if row["symbol"] in targets]
        logger.info("📊 %s symbols need fundamental enrichment", len(target_rows))

        required = required_preset_columns()
        failed: set[str] = set()
        if target_rows:
            try:
                enriched = enrich_rows(target_rows, required)
            except Exception as exc:  # noqa: BLE001 - keep the quote rows either way
                logger.error("Enrichment batch failed: %s", exc)
                failed = set(targets)
            else:
                by_symbol = {row["symbol"]: row for row in enriched}
                for row in rows:
                    update = by_symbol.get(row["symbol"])
                    if update is not None:
                        row.update(update)

        for row in rows:
            symbol = row["symbol"]
            store.save_stock(symbol, row)
            if symbol in targets:
                has_values = not required or any(
                    row.get(column) is not None for column in required
                )
                if not has_values:
                    failed.add(symbol)
                status = "failed" if symbol in failed else "success"
                error = "Enrichment unavailable" if symbol in failed else None
                store.update_sync_status(symbol, "fundamentals", status, error)

        logger.info(
            "✅ Synced %s symbols (%s enrichment failures)", len(rows), len(failed)
        )
    except Exception:
        logger.exception("💥 Critical error")


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
