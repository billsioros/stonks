"""Background worker to fetch and persist stock data on a recurring interval."""

import json
import logging
import random
import sqlite3
import time
from typing import Any

from stonks import alerts, sanity
from stonks.alerts import buy_opportunity_alerts, daily_move_alerts, evaluate_alerts
from stonks.config import DATA_DIR, WORKER_INTERVAL_MINUTES
from stonks.detail import load_page
from stonks.detail_parse import parse_overview
from stonks.hedgefollow import apply_flags, fetch_largest_buys
from stonks.stockanalysis import current_discount_rate, fetch_rows
from stonks.store import SQLiteStore, is_stock_row

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(DATA_DIR / "worker.log")],
)
logger = logging.getLogger("stonks.worker")

# Headlines per symbol per sync; a busy news day should not bury every other alert.
NEWS_ALERTS_PER_SYNC = 3

# A failed run retries quickly, then eases off; success restores the normal cadence.
RETRY_DELAYS_MINUTES = (1, 2, 4, 8, 15)
RETRY_JITTER_SECONDS = 10.0

_now = time.time


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


def _record_daily_move_alerts(
    store: SQLiteStore,
    watched: set[str],
    rows: list[dict[str, Any]],
    previous: dict[str, dict[str, Any]] | None = None,
) -> int:
    """Record 5% moves from each watched symbol's first price of the day."""
    day = alerts.day_bucket()
    try:
        state = json.loads(store.get_metadata("daily_move_baselines") or "null")
    except (TypeError, ValueError):
        state = None
    if state is None and previous:
        # No baseline has ever been recorded (fresh store, or a database from
        # before this feature): the snapshot this run replaces is the only
        # earlier price available, so treat it as the day's first price.
        state = {
            "day": day,
            "prices": {
                symbol: row["price"]
                for symbol, row in previous.items()
                if row.get("price") is not None
            },
        }
    watched_rows = [row for row in rows if row.get("symbol") in watched]
    fired, updated = daily_move_alerts(watched_rows, state, day=day)
    store.save_metadata("daily_move_baselines", json.dumps(updated))

    inserted = 0
    for alert in fired:
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
    """Re-run the reference-site checks on every sync and keep the verdicts.

    Checks read the stored snapshot, so they can still run after a failed sync.
    A broken check must never change the sync outcome we just recorded.
    """
    try:
        results = sanity.run_sanity_checks(store)
        try:
            next_check_at = float(store.get_metadata("next_sync_at") or "")
        except (OSError, sqlite3.Error, TypeError, ValueError):
            next_check_at = None
        sanity.save_report(store, results, next_check_at=next_check_at)
    except Exception:
        logger.exception("Cross-checks could not be refreshed")
        return
    diverged = [result.platform for result in results if result.ok is False]
    if diverged:
        logger.warning("⚠️ Cross-check diverged on: %s", ", ".join(diverged))
    else:
        logger.info("✅ Cross-checks agree with the reference sites")


def retry_delay_seconds(failures: int) -> float:
    """Seconds to wait after a run with this many consecutive failures."""
    base = WORKER_INTERVAL_MINUTES * 60
    if failures < 1 or failures > len(RETRY_DELAYS_MINUTES):
        return base
    return RETRY_DELAYS_MINUTES[failures - 1] * 60 + random.uniform(  # nosec B311
        0.0, RETRY_JITTER_SECONDS
    )


def _next_sync_delay(default: float | None = None) -> float:
    """Time left until the recorded next attempt, or a fallback delay."""
    fallback = WORKER_INTERVAL_MINUTES * 60 if default is None else default
    try:
        next_at = float(SQLiteStore().get_metadata("next_sync_at"))
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return fallback
    return min(max(0.0, next_at - _now()), WORKER_INTERVAL_MINUTES * 60)


def _record_sync_outcome(
    store: SQLiteStore, attempted_at: str, status: str, error: str
) -> None:
    """Persist the health of this sync so the UI can show staleness."""
    store.save_metadata("last_sync_status", status)
    store.save_metadata("last_sync_time", attempted_at)
    store.save_metadata("last_sync_error", error)
    if status == "success":
        store.save_metadata("last_successful_sync_at", attempted_at)
        failures = 0
    else:
        try:
            failures = int(store.get_metadata("sync_failure_count") or 0) + 1
        except (TypeError, ValueError):
            failures = 1
    store.save_metadata("sync_failure_count", str(failures))
    store.save_metadata("next_sync_at", str(_now() + retry_delay_seconds(failures)))


def job() -> None:
    """Sync the full StockAnalysis screener dataset into the local store."""
    logger.info("🚀 Starting data sync...")
    store: SQLiteStore | None = None
    attempted_at = str(_now())
    try:
        store = SQLiteStore()
        # Hold a conservative lease until the outcome is known, so a restart
        # mid-fetch cannot immediately hit the providers again.
        store.save_metadata("next_sync_at", str(_now() + WORKER_INTERVAL_MINUTES * 60))
        # Alerts are transient; nothing older than the retention window is useful.
        store.prune_alerts()
        held = set(store.get_position_symbols())
        stored = _watched_rows(store, set(store.get_monitored_symbols()))
        priced = {
            symbol
            for symbol, row in stored.items()
            if is_stock_row(row) or symbol in held
        }
        previous = {symbol: stored[symbol] for symbol in priced}
        news_symbols = sorted((set(store.get_watchlist_symbols()) & priced) | held)
        # Headlines come from the cached overview page, not the screener
        # snapshot, so a failed refresh must not starve news alerts.
        news = fetch_watched_news(store, news_symbols)

        try:
            discount_rate = current_discount_rate()
        except OSError as exc:
            raise OSError(f"Treasury yield lookup failed: {exc}") from exc
        logger.info("📉 DCF discount rate: %.0f%%", discount_rate * 100)
        try:
            rows = fetch_rows(discount_rate=discount_rate)
        except OSError as exc:
            raise OSError(f"StockAnalysis screener fetch failed: {exc}") from exc
        if not rows:
            logger.warning("⚠️ No screener data found.")
            _record_sync_outcome(
                store,
                attempted_at,
                "failed",
                "No screener data returned from provider",
            )
            return

        try:
            largest_buys = fetch_largest_buys()
        except OSError as exc:
            raise OSError(f"HedgeFollow largest-buys fetch failed: {exc}") from exc
        if largest_buys is None:
            logger.warning("⚠️ HedgeFollow buys unavailable; flag left unknown")
        else:
            matched = apply_flags(rows, largest_buys)
            logger.info(
                "🐋 %s symbols in HedgeFollow's largest %s buys",
                matched,
                len(largest_buys),
            )

        # Held symbols can sit outside the screener universe (for example an
        # ETF). Keep their last known quote so valuation and alerts survive a
        # refresh that does not return them.
        fetched_symbols = {row.get("symbol") for row in rows}
        rows.extend(
            stored[symbol]
            for symbol in sorted(held)
            if symbol in stored and symbol not in fetched_symbols
        )
        store.replace_stocks(rows)
        store.save_metadata("universe_size", len(rows))
        _record_sync_outcome(store, attempted_at, "success", "")

        changed = _record_change_alerts(store, priced, previous, rows)
        buy_opps = 0
        for alert in buy_opportunity_alerts(rows):
            if store.add_alert(
                alert.symbol,
                alert.kind,
                alert.severity,
                alert.title,
                alert.detail,
                alert.dedupe_key,
            ):
                buy_opps += 1
        daily_moves = _record_daily_move_alerts(store, priced, rows, previous)
        if daily_moves:
            logger.info("🔔 %s daily-move alerts", daily_moves)
        if changed or news or buy_opps:
            logger.info(
                "🔔 %s change alerts, %s news alerts, %s buy-opportunity alerts",
                changed,
                news,
                buy_opps,
            )

        logger.info("✅ Synced %s symbols", len(rows))
    except Exception as exc:
        logger.exception("💥 Critical error")
        if store is not None:
            _record_sync_outcome(store, attempted_at, "failed", str(exc))
    finally:
        if store is not None:
            _maybe_run_sanity_checks(store)


def run_worker() -> None:
    """Run the worker loop, waiting only as long as the last outcome requires."""
    logger.info("🏁 Worker initialized.")

    pending = _next_sync_delay(default=0.0)
    if pending > 0:
        time.sleep(pending)

    while True:
        job()
        time.sleep(_next_sync_delay())


if __name__ == "__main__":
    run_worker()
