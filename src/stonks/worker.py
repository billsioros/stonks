"""Background worker to fetch and persist stock data on a recurring interval."""

import logging
import time
from typing import Any

import schedule

from stonks.config import (
    DATA_DIR,
    WORKER_BATCH_COOLDOWN,
    WORKER_BATCH_SIZE,
    WORKER_INTERVAL_MINUTES,
    WORKER_MAX_ATTEMPTS,
    WORKER_RETRY_BASE_DELAY,
    WORKER_SCREENER_ATTEMPTS,
    YAHOO_ENRICHMENT_TTL_DAYS,
)
from stonks.store import SQLiteStore
from stonks.yahoo import enrich_rows, preset_candidate_rows, required_preset_columns

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(DATA_DIR / "worker.log")],
)
logger = logging.getLogger("stonks.worker")


def _backoff_for(attempts: int) -> float:
    """Escalating delay before a symbol's next retry, capped at 5 minutes."""
    return min(WORKER_RETRY_BASE_DELAY * (2**attempts), 300.0)


def _fetch_candidates() -> list[dict[str, Any]]:
    """Fetch screener candidates, retrying rate-limited calls with backoff."""
    delay = WORKER_RETRY_BASE_DELAY
    last_error: Exception | None = None
    for attempt in range(1, WORKER_SCREENER_ATTEMPTS + 1):
        try:
            return preset_candidate_rows()
        except Exception as exc:  # noqa: BLE001 - Yahoo fails in many ways
            last_error = exc
            if attempt < WORKER_SCREENER_ATTEMPTS:
                logger.warning(
                    "Screener attempt %s/%s failed (%s); retrying in %.1fs",
                    attempt,
                    WORKER_SCREENER_ATTEMPTS,
                    exc,
                    delay,
                )
                time.sleep(delay)
                delay *= 2
    raise last_error  # type: ignore[misc]


def job() -> None:
    """Sync Yahoo screener quotes and enriched fundamentals into the local store."""
    logger.info("🚀 Starting data sync...")
    try:
        store = SQLiteStore()
        try:
            rows = _fetch_candidates()
        except Exception as exc:  # noqa: BLE001 - keep the DB untouched on failure
            logger.error(
                "Screener unavailable after %s attempts: %s",
                WORKER_SCREENER_ATTEMPTS,
                exc,
            )
            return
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
        failed_state = store.get_failed_attempts("fundamentals")
        now = time.time()
        retry_due = {
            symbol
            for symbol, (attempts, last) in failed_state.items()
            if attempts < WORKER_MAX_ATTEMPTS and now - last >= _backoff_for(attempts)
        }
        # Failed symbols whose backoff has not elapsed (or that hit the attempt
        # cap) are deferred even when they also look unsynced or stale.
        deferred = set(failed_state) - retry_due
        targets = (
            (all_symbols - synced) | (stale & all_symbols) | (retry_due & all_symbols)
        ) - deferred
        target_rows = [row for row in rows if row["symbol"] in targets]
        logger.info("📊 %s symbols need fundamental enrichment", len(target_rows))

        required = required_preset_columns()
        batched = [
            target_rows[i : i + WORKER_BATCH_SIZE]
            for i in range(0, len(target_rows), WORKER_BATCH_SIZE)
        ]
        total_failed = 0
        for batch_number, batch in enumerate(batched, start=1):
            transport_failed: set[str] = set()
            by_symbol: dict[str, dict[str, Any]] = {}
            if batch:
                try:
                    enriched = enrich_rows(batch, required)
                except Exception as exc:  # noqa: BLE001 - keep cached quote rows
                    logger.error("Enrichment batch %s failed: %s", batch_number, exc)
                    transport_failed = {row["symbol"] for row in batch}
                else:
                    by_symbol = {row["symbol"]: row for row in enriched}

            # Checkpoint each batch so an interrupted run keeps its progress.
            for row in batch:
                symbol = row["symbol"]
                update = by_symbol.get(symbol)
                if update is not None:
                    row.update(update)
                store.save_stock(symbol, row)

                has_values = not required or any(
                    row.get(column) is not None for column in required
                )
                previous, _ = failed_state.get(symbol, (0, 0.0))
                if symbol in transport_failed:
                    # A rate limit is a transport error, not a per-symbol data
                    # gap: leave the attempt count untouched so it stays
                    # retryable at the next interval instead of being capped.
                    attempts = previous
                    error = "Enrichment transport error"
                elif has_values:
                    store.update_sync_status(symbol, "fundamentals", "success")
                    continue
                else:
                    attempts = previous + 1
                    error = "Enrichment unavailable"
                    if attempts >= WORKER_MAX_ATTEMPTS:
                        logger.warning(
                            "Giving up on %s after %s attempts", symbol, attempts
                        )
                total_failed += 1
                store.update_sync_status(
                    symbol,
                    "fundamentals",
                    "failed",
                    error,
                    attempts=attempts,
                    backoff_seconds=_backoff_for(attempts),
                )

            if batch_number < len(batched):
                logger.info(
                    "Batch %s/%s checkpointed; cooling down %.1fs",
                    batch_number,
                    len(batched),
                    WORKER_BATCH_COOLDOWN,
                )
                time.sleep(WORKER_BATCH_COOLDOWN)

        # Basic quote rows for non-target symbols still need persisting.
        for row in rows:
            if row["symbol"] not in targets:
                store.save_stock(row["symbol"], row)

        logger.info(
            "✅ Synced %s symbols (%s enrichment failures)", len(rows), total_failed
        )
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
