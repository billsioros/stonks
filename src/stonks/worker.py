"""Background worker to fetch and persist stock data on a recurring interval."""

import logging
import time
from typing import Any

import schedule

from stonks import sanity
from stonks.alerts import evaluate_alerts
from stonks.config import DATA_DIR, WORKER_INTERVAL_MINUTES
from stonks.detail import load_page
from stonks.detail_parse import parse_overview
from stonks.hedgefollow import apply_flags, fetch_largest_buys
from stonks.stockanalysis import current_discount_rate, fetch_rows
from stonks.store import SQLiteStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(DATA_DIR / "worker.log")],
)
logger = logging.getLogger("stonks.worker")

# Headlines per symbol per sync; a busy news day should not bury every other alert.
NEWS_ALERTS_PER_SYNC = 3


def _watched_rows(store: SQLiteStore, symbols: set[str]) -> dict[str, dict[str, Any]]:
    """Snapshot the watched symbols' screener rows before they are replaced."""
    if not symbols:
        return {}
    rows, _, _ = store.get_stocks(
        filters={"symbol": {"values": sorted(symbols)}},
        page_size=len(symbols),
    )
    return {row["symbol"]: row for row in rows}


def _record_change_alerts(
    store: SQLiteStore,
    watched: set[str],
    previous: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
) -> int:
    """Compare the fresh snapshot with the previous one and store the alerts."""
    inserted = 0
    for row in rows:
        symbol = row.get("symbol")
        if symbol not in watched:
            continue
        for alert in evaluate_alerts(previous.get(symbol), row):
            if store.add_alert(
                alert.symbol,
                alert.kind,
                alert.severity,
                alert.title,
                alert.detail,
                alert.dedupe_key,
            ):
                inserted += 1
    return inserted


def fetch_watched_news(store: SQLiteStore, symbols: list[str]) -> int:
    """Record unseen StockAnalysis headlines for the watched symbols.

    The overview payload is already cached for the detail page, so this reuses
    it instead of hitting the provider once per symbol per sync.
    """
    inserted = 0
    for symbol in symbols:
        payload, _ = load_page(store, symbol, "overview")
        if not payload:
            continue
        articles = parse_overview(payload).get("news") or []
        for article in articles[:NEWS_ALERTS_PER_SYNC]:
            url = article.get("url")
            title = article.get("title")
            if not url or not title:
                continue
            detail = " · ".join(
                part for part in (article.get("source"), article.get("ago")) if part
            )
            if store.add_alert(
                symbol,
                "news",
                "info",
                str(title),
                detail or None,
                f"{symbol}:news:{url}",
            ):
                inserted += 1
    return inserted


def _maybe_run_sanity_checks(store: SQLiteStore) -> None:
    """Re-run the reference-site checks every few hours and keep the verdicts."""
    if sanity.report_is_fresh(sanity.load_report(store)):
        return
    results = sanity.run_sanity_checks(store)
    sanity.save_report(store, results)
    diverged = [result.platform for result in results if result.ok is False]
    if diverged:
        logger.warning("⚠️ Cross-check diverged on: %s", ", ".join(diverged))
    else:
        logger.info("✅ Cross-checks agree with the reference sites")


def job() -> None:
    """Sync the full StockAnalysis screener dataset into the local store."""
    logger.info("🚀 Starting data sync...")
    try:
        store = SQLiteStore()
        # Alerts are transient; nothing older than the retention window is useful.
        store.prune_alerts()
        watched = set(store.get_watchlist_symbols())
        previous = _watched_rows(store, watched)

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

        store.replace_stocks(rows)
        store.save_metadata("universe_size", len(rows))

        changed = _record_change_alerts(store, watched, previous, rows)
        news = fetch_watched_news(store, sorted(watched))
        if changed or news:
            logger.info("🔔 %s change alerts, %s news alerts", changed, news)

        _maybe_run_sanity_checks(store)

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
