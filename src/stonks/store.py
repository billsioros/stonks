"""SQLiteStore — persists saved screens and watchlists."""

import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Self

from stonks.config import DB_PATH

VALUATION_COLUMNS = (
    "dcf_fair_value",
    "dcf_upside_pct",
    "lynch_fair_value",
    "lynch_upside_pct",
)

# Inputs persisted beside the fair values so GuruFocus checks can recompute the
# DCF model from the same data the screener used.
DCF_INPUT_COLUMNS = ("eps_growth_10y_pct", "dcf_discount_rate_pct")

# 1 when the symbol is in HedgeFollow's largest hedge fund buys, 0 when not, NULL
# when the list could not be read during that sync.
FLAG_COLUMNS = ("hedge_fund_buys",)

# Normalised and composite metrics that live beside the original columns so the
# reference-site benchmarks keep reading unmutated values.
NEW_COLUMNS = (
    "shares_insiders_percent",
    "cyclical_peak_risk",
    "valuation_triangulation",
    "valuation_upside_capped_pct",
)

_NEW_COLUMN_TYPES = {
    "shares_insiders_percent": "REAL",
    "cyclical_peak_risk": "INTEGER",
    "valuation_triangulation": "TEXT",
    "valuation_upside_capped_pct": "REAL",
}

STOCK_FIELDS = [
    "symbol",
    "description",
    "exchange",
    "type",
    "mic",
    "currency",
    "market_cap",
    "pe_ratio",
    "pb_ratio",
    "ps_ratio",
    "peg_ratio",
    "ev_to_ebitda",
    "dividend_yield_pct",
    "gross_margin_pct",
    "operating_margin_pct",
    "net_margin_pct",
    "roa_pct",
    "roe_pct",
    "roic_pct",
    "current_ratio",
    "debt_to_equity",
    "fcf_margin_pct",
    "revenue_growth_5y_pct",
    "eps_growth_5y_pct",
    "eps_growth_10y_pct",
    "beta",
    "price",
    "week_52_high",
    "week_52_low",
    "revenue_growth_3y_pct",
    "eps_growth_3y_pct",
    "free_cash_flow_per_share",
    "revenue_per_share",
    "book_value_per_share",
    "tangible_book_value_per_share",
    "long_term_debt_to_equity",
    "asset_turnover",
    "eps_ttm",
    "net_income",
    "free_cash_flow",
    "fcf_growth_5y_pct",
    "net_income_growth_5y_pct",
    "return_cagr_5y_pct",
    "return_cagr_10y_pct",
    "return_cagr_15y_pct",
    "roa_5y_avg_pct",
    "roe_5y_avg_pct",
    "roic_5y_avg_pct",
    "shares_insiders_pct",
    "shares_insiders_percent",
    "industry",
    "short_pct",
    "rating",
    "pt_upside_pct",
    "cyclical_peak_risk",
    "valuation_triangulation",
    "valuation_upside_capped_pct",
    *VALUATION_COLUMNS,
    *DCF_INPUT_COLUMNS,
    *FLAG_COLUMNS,
]


def _finite_bound(
    column: str, value: Any, bound: str, warnings: list[str]
) -> float | None:
    """Coerce one filter bound to a finite float, recording why it was dropped."""
    if value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        warnings.append(f"Ignored non-numeric {bound} bound on '{column}'")
        return None
    if not math.isfinite(number):
        warnings.append(f"Ignored non-finite {bound} bound on '{column}'")
        return None
    return number


class StockQueryResult(tuple[Any, ...]):
    """3-tuple of (rows, total_pages, total_matching) with query warnings."""

    rows: list[dict[str, Any]]
    total_pages: int
    total_matching: int
    warnings: list[str]

    def __new__(
        cls,
        rows: list[dict[str, Any]],
        total_pages: int,
        total_matching: int,
        warnings: list[str] | None = None,
    ) -> Self:
        instance = super().__new__(cls, (rows, total_pages, total_matching))
        instance.rows = rows
        instance.total_pages = total_pages
        instance.total_matching = total_matching
        instance.warnings = warnings or []
        return instance


class SQLiteStore:
    """Lightweight persistence layer using SQLite for screens and watchlists."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path))

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS saved_screens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    filters TEXT NOT NULL,
                    view_preset TEXT,
                    sort_column TEXT,
                    sort_ascending INTEGER DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS saved_backtests (
                    name TEXT PRIMARY KEY,
                    settings TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol TEXT PRIMARY KEY,
                    added_at REAL NOT NULL,
                    notes TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_status (
                    symbol TEXT,
                    sync_type TEXT,
                    status TEXT,
                    error TEXT,
                    last_attempt REAL,
                    attempts INTEGER DEFAULT 0,
                    next_retry_at REAL,
                    PRIMARY KEY (symbol, sync_type)
                )
            """)
            # Existing databases predate the retry-tracking columns.
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sync_status)")}
            if "attempts" not in columns:
                conn.execute(
                    "ALTER TABLE sync_status ADD COLUMN attempts INTEGER DEFAULT 0"
                )
            if "next_retry_at" not in columns:
                conn.execute("ALTER TABLE sync_status ADD COLUMN next_retry_at REAL")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kv_cache (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    expires_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL,
                    seen_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stocks (
                    symbol TEXT PRIMARY KEY,
                    description TEXT,
                    exchange TEXT,
                    type TEXT,
                    mic TEXT,
                    currency TEXT,
                    market_cap REAL,
                    pe_ratio REAL,
                    pb_ratio REAL,
                    ps_ratio REAL,
                    peg_ratio REAL,
                    ev_to_ebitda REAL,
                    dividend_yield_pct REAL,
                    gross_margin_pct REAL,
                    operating_margin_pct REAL,
                    net_margin_pct REAL,
                    roa_pct REAL,
                    roe_pct REAL,
                    roic_pct REAL,
                    current_ratio REAL,
                    debt_to_equity REAL,
                    fcf_margin_pct REAL,
                    revenue_growth_5y_pct REAL,
                    eps_growth_5y_pct REAL,
                    beta REAL,
                    price REAL,
                    week_52_high REAL,
                    week_52_low REAL,
                    revenue_growth_3y_pct REAL,
                    eps_growth_3y_pct REAL,
                    free_cash_flow_per_share REAL,
                    revenue_per_share REAL,
                    book_value_per_share REAL,
                    tangible_book_value_per_share REAL,
                    long_term_debt_to_equity REAL,
                    asset_turnover REAL,
                    eps_ttm REAL,
                    eps_growth_10y_pct REAL,
                    dcf_discount_rate_pct REAL,
                    net_income REAL,
                    free_cash_flow REAL,
                    fcf_growth_5y_pct REAL,
                    net_income_growth_5y_pct REAL,
                    return_cagr_5y_pct REAL,
                    return_cagr_10y_pct REAL,
                    return_cagr_15y_pct REAL,
                    roa_5y_avg_pct REAL,
                    roe_5y_avg_pct REAL,
                    roic_5y_avg_pct REAL,
                    shares_insiders_pct REAL,
                    shares_insiders_percent REAL,
                    industry TEXT,
                    short_pct REAL,
                    rating TEXT,
                    pt_upside_pct REAL,
                    dcf_fair_value REAL,
                    dcf_upside_pct REAL,
                    lynch_fair_value REAL,
                    lynch_upside_pct REAL,
                    hedge_fund_buys INTEGER,
                    cyclical_peak_risk INTEGER,
                    valuation_triangulation TEXT,
                    valuation_upside_capped_pct REAL,
                    updated_at REAL
                )
            """)
            # Existing databases predate the valuation columns.
            stock_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(stocks)")
            }
            for column in (*VALUATION_COLUMNS, *DCF_INPUT_COLUMNS):
                if column not in stock_columns:
                    conn.execute(
                        f"ALTER TABLE stocks ADD COLUMN {column} REAL"  # nosec B608
                    )
            for column in FLAG_COLUMNS:
                if column not in stock_columns:
                    conn.execute(
                        f"ALTER TABLE stocks ADD COLUMN {column} INTEGER"  # nosec B608
                    )
            self._migrate_schema(conn)
            conn.commit()

    @staticmethod
    def _migrate_schema(conn: sqlite3.Connection) -> None:
        """Add the side-by-side metrics and backfill them on existing databases."""
        stock_columns = {row[1] for row in conn.execute("PRAGMA table_info(stocks)")}
        for column_name in NEW_COLUMNS:
            if column_name not in stock_columns:
                column_type = _NEW_COLUMN_TYPES[column_name]
                conn.execute(
                    f"ALTER TABLE stocks ADD COLUMN {column_name} {column_type}"  # nosec B608
                )

        # Backfill the true percentage from the fraction the benchmark checks use.
        conn.execute("""
            UPDATE stocks
            SET shares_insiders_percent = shares_insiders_pct * 100.0
            WHERE shares_insiders_percent IS NULL AND shares_insiders_pct IS NOT NULL
        """)
        conn.commit()

    # ── Saved Screens ────────────────────────────────────────────────

    def save_screen(
        self,
        name: str,
        filters: dict[str, Any],
        view_preset: str = "Overview",
        sort_column: str | None = None,
        sort_ascending: bool = True,
    ) -> None:
        """Save or update a screen preset."""
        now = time.time()
        filters_json = json.dumps(filters)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO saved_screens (name, filters, view_preset, sort_column, sort_ascending, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     filters=excluded.filters,
                     view_preset=excluded.view_preset,
                     sort_column=excluded.sort_column,
                     sort_ascending=excluded.sort_ascending,
                     updated_at=excluded.updated_at
                """,
                (
                    name,
                    filters_json,
                    view_preset,
                    sort_column,
                    int(sort_ascending),
                    now,
                    now,
                ),
            )
            conn.commit()

    def list_screens(self) -> list[dict[str, Any]]:
        """Return all saved screens."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, filters, view_preset, sort_column, sort_ascending, created_at, updated_at FROM saved_screens ORDER BY updated_at DESC"
            ).fetchall()
        return [
            {
                "id": r[0],
                "name": r[1],
                "filters": json.loads(r[2]),
                "view_preset": r[3],
                "sort_column": r[4],
                "sort_ascending": bool(r[5]),
                "created_at": r[6],
                "updated_at": r[7],
            }
            for r in rows
        ]

    def delete_screen(self, name: str) -> None:
        """Delete a saved screen."""
        with self._connect() as conn:
            conn.execute("DELETE FROM saved_screens WHERE name=?", (name,))
            conn.commit()

    # ── Saved Backtests ──────────────────────────────────────────────

    def save_backtest(self, name: str, settings: dict[str, Any]) -> None:
        """Save or update a backtest configuration (symbols, weights, dates)."""
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO saved_backtests (name, settings, created_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     settings=excluded.settings,
                     updated_at=excluded.updated_at
                """,
                (name, json.dumps(settings), now, now),
            )
            conn.commit()

    def list_backtests(self) -> list[dict[str, Any]]:
        """Return saved backtest settings, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, settings, created_at, updated_at FROM saved_backtests ORDER BY updated_at DESC"
            ).fetchall()
        return [
            {
                "name": row[0],
                "settings": json.loads(row[1]),
                "created_at": row[2],
                "updated_at": row[3],
            }
            for row in rows
        ]

    def delete_backtest(self, name: str) -> None:
        """Delete a saved backtest."""
        with self._connect() as conn:
            conn.execute("DELETE FROM saved_backtests WHERE name=?", (name,))
            conn.commit()

    # ── Watchlist ────────────────────────────────────────────────────

    def add_to_watchlist(self, symbol: str, notes: str = "") -> None:
        """Add a symbol to the watchlist."""
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO watchlist (symbol, added_at, notes)
                   VALUES (?, ?, ?)
                   ON CONFLICT(symbol) DO UPDATE SET notes=excluded.notes
                """,
                (symbol, now, notes),
            )
            conn.commit()

    def remove_from_watchlist(self, symbol: str) -> None:
        """Remove a symbol from the watchlist."""
        with self._connect() as conn:
            conn.execute("DELETE FROM watchlist WHERE symbol=?", (symbol,))
            conn.commit()

    def get_watchlist(self) -> list[dict[str, Any]]:
        """Return all watchlist symbols."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT symbol, added_at, notes FROM watchlist ORDER BY added_at DESC"
            ).fetchall()
        return [{"symbol": r[0], "added_at": r[1], "notes": r[2]} for r in rows]

    def get_watchlist_symbols(self) -> list[str]:
        """Return just the list of ticker symbols in the watchlist."""
        with self._connect() as conn:
            rows = conn.execute("SELECT symbol FROM watchlist").fetchall()
        return [r[0] for r in rows]

    def get_watchlist_rows(self) -> list[dict[str, Any]]:
        """Return watchlist symbols joined to their stored sector and market cap."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT w.symbol, s.industry, s.market_cap
                   FROM watchlist w LEFT JOIN stocks s ON s.symbol = w.symbol
                   ORDER BY w.symbol"""
            ).fetchall()
        return [
            {"symbol": row[0], "industry": row[1], "market_cap": row[2]} for row in rows
        ]

    def get_hedge_buy_symbols(self) -> list[str]:
        """Return the symbols currently flagged as a largest hedge fund buy."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT symbol FROM stocks WHERE hedge_fund_buys = 1"
            ).fetchall()
        return [r[0] for r in rows]

    # ── Sync Status ──────────────────────────────────────────────────

    def update_sync_status(
        self,
        symbol: str,
        sync_type: str,
        status: str,
        error: str | None = None,
        attempts: int = 0,
        backoff_seconds: float = 0.0,
    ) -> None:
        """Update the sync status for a symbol, including retry bookkeeping."""
        now = time.time()
        next_retry_at = now + backoff_seconds if backoff_seconds > 0 else None
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO sync_status
                   (symbol, sync_type, status, error, last_attempt, attempts, next_retry_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(symbol, sync_type) DO UPDATE SET
                     status=excluded.status,
                     error=excluded.error,
                     last_attempt=excluded.last_attempt,
                     attempts=excluded.attempts,
                     next_retry_at=excluded.next_retry_at
                """,
                (symbol, sync_type, status, error, now, attempts, next_retry_at),
            )
            conn.commit()

    def get_stale_symbols(self, sync_type: str, stale_hours: int = 24 * 7) -> list[str]:
        """Return symbols that were successfully synced but are stale."""
        cutoff = time.time() - (stale_hours * 3600)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT symbol FROM sync_status
                   WHERE sync_type=? AND status='success' AND last_attempt < ?""",
                (sync_type, cutoff),
            ).fetchall()
        return [r[0] for r in rows]

    def get_synced_symbols(self, sync_type: str) -> list[str]:
        """Return symbols that were successfully synced."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT symbol FROM sync_status WHERE sync_type=? AND status='success'",
                (sync_type,),
            ).fetchall()
        return [r[0] for r in rows]

    def get_last_sync_info(self) -> dict[str, Any]:
        """Return general stats about the last sync."""
        with self._connect() as conn:
            # Prefer the explicit universe size from metadata if available
            stored_universe = self.get_metadata("universe_size")
            if stored_universe:
                total_universe = int(stored_universe)
            else:
                total_universe = conn.execute(
                    "SELECT COUNT(DISTINCT symbol) FROM sync_status"
                ).fetchone()[0]

            success_fundamentals = conn.execute(
                "SELECT COUNT(*) FROM sync_status WHERE status='success' AND sync_type='fundamentals'"
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM sync_status WHERE status='failed'"
            ).fetchone()[0]
            last_run = conn.execute(
                "SELECT MAX(last_attempt) FROM sync_status"
            ).fetchone()[0]

        return {
            "total_symbols": total_universe,
            "success_count": success_fundamentals,
            "fundamentals_count": success_fundamentals,
            "failed_count": failed,
            "last_run": last_run,
        }

    # ── Metadata ─────────────────────────────────────────────────────

    def save_metadata(self, key: str, value: Any) -> None:
        """Save a piece of global metadata."""
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO metadata (key, value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                     value=excluded.value,
                     updated_at=excluded.updated_at
                """,
                (key, str(value), now),
            )
            conn.commit()

    def get_metadata(self, key: str) -> str | None:
        """Retrieve a piece of global metadata."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM metadata WHERE key=?", (key,)
            ).fetchone()
        return row[0] if row else None

    # ── Cache ─────────────────────────────────────────────────────────

    def cache_set(self, key: str, value: Any, ttl_seconds: float) -> None:
        """Store a JSON-serialisable value under `key` with a time to live."""
        expires_at = time.time() + ttl_seconds
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO kv_cache (key, value, expires_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                     value=excluded.value, expires_at=excluded.expires_at
                """,
                (key, json.dumps(value), expires_at),
            )
            conn.commit()

    def cache_get(self, key: str, *, allow_expired: bool = False) -> Any:
        """Return a cached value, or None when missing, expired or unreadable.

        ``allow_expired`` returns a stale entry too, which callers use as a
        fallback when the provider cannot be reached.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM kv_cache WHERE key=?", (key,)
            ).fetchone()
        if row is None or row[1] is None:
            return None
        if not allow_expired and row[1] < time.time():
            return None
        try:
            return json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return None

    def cache_delete(self, key: str) -> None:
        """Drop a cached value."""
        with self._connect() as conn:
            conn.execute("DELETE FROM kv_cache WHERE key=?", (key,))
            conn.commit()

    # ── Alerts ───────────────────────────────────────────────────────

    def add_alert(
        self,
        symbol: str,
        kind: str,
        severity: str,
        title: str,
        detail: str | None,
        dedupe_key: str,
    ) -> bool:
        """Insert an alert unless its dedupe key was already recorded."""
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO alerts
                   (symbol, kind, severity, title, detail, dedupe_key, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (symbol, kind, severity, title, detail, dedupe_key, time.time()),
            )
            conn.commit()
        return cursor.rowcount > 0

    def get_alerts(
        self,
        *,
        unread_only: bool = True,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return alerts newest first, unread only unless told otherwise."""
        where = []
        params: list[Any] = []
        if unread_only:
            where.append("seen_at IS NULL")
        if symbol is not None:
            where.append("symbol = ?")
            params.append(symbol)
        where_sql = " AND ".join(where) if where else "1=1"
        query = (
            "SELECT id, symbol, kind, severity, title, detail, "
            "dedupe_key, created_at, seen_at "
            f"FROM alerts WHERE {where_sql} "  # nosec B608
            "ORDER BY created_at DESC, id DESC LIMIT ?"
        )
        with self._connect() as conn:
            rows = conn.execute(query, [*params, limit]).fetchall()
        return [
            {
                "id": r[0],
                "symbol": r[1],
                "kind": r[2],
                "severity": r[3],
                "title": r[4],
                "detail": r[5],
                "dedupe_key": r[6],
                "created_at": r[7],
                "seen_at": r[8],
            }
            for r in rows
        ]

    def mark_alerts_seen(self, ids: list[int]) -> None:
        """Mark the given alerts as read."""
        if not ids:
            return
        placeholders = ",".join(["?"] * len(ids))
        query = f"UPDATE alerts SET seen_at = ? WHERE id IN ({placeholders})"  # nosec B608
        with self._connect() as conn:
            conn.execute(query, [time.time(), *ids])
            conn.commit()

    def unread_alert_counts(self) -> dict[str, int]:
        """Unread alert count per symbol, for the watchlist marker column."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT symbol, COUNT(*) FROM alerts
                   WHERE seen_at IS NULL GROUP BY symbol"""
            ).fetchall()
        return {r[0]: int(r[1]) for r in rows}

    def count_unread_alerts(self) -> int:
        """How many alerts have not been read yet."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE seen_at IS NULL"
            ).fetchone()
        return int(row[0])

    def prune_alerts(self, older_than_days: int = 14) -> int:
        """Drop alerts older than the retention window."""
        cutoff = time.time() - older_than_days * 86400
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM alerts WHERE created_at < ?", (cutoff,))
            conn.commit()
        return cursor.rowcount

    def get_buy_opportunities(self, limit: int = 20) -> list[dict[str, Any]]:
        """Screener stocks near their 52-week low, strongest first.

        "Historically low" here means within 5% of the 52-week low. Stocks below
        both DCF and Peter Lynch fair value estimates are ranked first.
        """
        limit = max(1, min(int(limit), 100))
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT symbol, description, price, week_52_low,
                       dcf_fair_value, lynch_fair_value,
                       dcf_upside_pct, lynch_upside_pct
                FROM stocks
                WHERE price > 0 AND week_52_low > 0
                  AND price <= week_52_low * 1.05
                ORDER BY
                    CASE
                        WHEN dcf_fair_value IS NOT NULL
                         AND lynch_fair_value IS NOT NULL
                         AND price <= dcf_fair_value
                         AND price <= lynch_fair_value
                        THEN 0 ELSE 1
                    END,
                    (price / week_52_low) ASC,
                    COALESCE(dcf_upside_pct, -999999) DESC,
                    COALESCE(lynch_upside_pct, -999999) DESC
                LIMIT ?
                """,
                (limit,),
            )
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ── Stocks ────────────────────────────────────────────────────────

    def get_stocks(
        self,
        filters: dict[str, Any] | None = None,
        search_query: str = "",
        sort_column: str | None = None,
        sort_ascending: bool = True,
        page: int = 1,
        page_size: int = 25,
    ) -> StockQueryResult:
        """Query stocks with filters, search, sort, pagination at DB level.

        Returns:
            A 3-tuple of (rows, total_pages, total_matching) that also exposes
            the filter diagnostics collected while building the query.
        """
        warnings: list[str] = []
        params: list[Any] = []
        where_clauses: list[str] = []

        numeric_columns = {
            "market_cap",
            "pe_ratio",
            "pb_ratio",
            "ps_ratio",
            "peg_ratio",
            "ev_to_ebitda",
            "dividend_yield_pct",
            "gross_margin_pct",
            "operating_margin_pct",
            "net_margin_pct",
            "roa_pct",
            "roe_pct",
            "roic_pct",
            "current_ratio",
            "debt_to_equity",
            "fcf_margin_pct",
            "revenue_growth_5y_pct",
            "eps_growth_5y_pct",
            *DCF_INPUT_COLUMNS,
            "beta",
            "price",
            "revenue_growth_3y_pct",
            "eps_growth_3y_pct",
            "free_cash_flow_per_share",
            "revenue_per_share",
            "book_value_per_share",
            "tangible_book_value_per_share",
            "long_term_debt_to_equity",
            "asset_turnover",
            "eps_ttm",
            "net_income",
            "free_cash_flow",
            "fcf_growth_5y_pct",
            "net_income_growth_5y_pct",
            "return_cagr_5y_pct",
            "return_cagr_10y_pct",
            "return_cagr_15y_pct",
            "roa_5y_avg_pct",
            "roe_5y_avg_pct",
            "roic_5y_avg_pct",
            "shares_insiders_pct",
            "shares_insiders_percent",
            "cyclical_peak_risk",
            "valuation_upside_capped_pct",
            "short_pct",
            "pt_upside_pct",
            *VALUATION_COLUMNS,
            *FLAG_COLUMNS,
        }
        # "symbol" is not an enum column, but callers legitimately need to
        # constrain the query to an explicit list (e.g. the watchlist).
        enum_columns = {
            "exchange",
            "type",
            "currency",
            "mic",
            "symbol",
            "valuation_triangulation",
        }

        if filters:
            for col, spec in filters.items():
                if not isinstance(spec, dict):
                    warnings.append(
                        f"Invalid filter specification for '{col}': expected dict"
                    )
                    continue
                if col in numeric_columns:
                    parsed_min = _finite_bound(col, spec.get("min"), "min", warnings)
                    parsed_max = _finite_bound(col, spec.get("max"), "max", warnings)

                    if (
                        parsed_min is not None
                        and parsed_max is not None
                        and parsed_min > parsed_max
                    ):
                        warnings.append(
                            f"Filter '{col}' has min ({parsed_min}) > max "
                            f"({parsed_max}); matches 0 rows"
                        )
                        where_clauses.append("1=0")
                    else:
                        if parsed_min is not None:
                            where_clauses.append(f"{col} >= ?")
                            params.append(parsed_min)
                        if parsed_max is not None:
                            where_clauses.append(f"{col} <= ?")
                            params.append(parsed_max)
                elif col in enum_columns:
                    if "values" in spec:
                        values = spec["values"]
                        if not values:
                            # An empty selection means "none of them", not "all".
                            where_clauses.append("1=0")
                        else:
                            placeholders = ",".join(["?"] * len(values))
                            where_clauses.append(f"{col} IN ({placeholders})")
                            params.extend(values)
                else:
                    warnings.append(f"Ignored unknown filter column: '{col}'")

        if search_query:
            q = f"%{search_query.strip().upper()}%"
            where_clauses.append("(symbol LIKE ? OR description LIKE ?)")
            params.extend([q, q])

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        base_columns = [
            "symbol",
            "description",
            "exchange",
            "type",
            "mic",
            "currency",
            "market_cap",
            "pe_ratio",
            "pb_ratio",
            "ps_ratio",
            "peg_ratio",
            "ev_to_ebitda",
            "dividend_yield_pct",
            "gross_margin_pct",
            "operating_margin_pct",
            "net_margin_pct",
            "roa_pct",
            "roe_pct",
            "roic_pct",
            "current_ratio",
            "debt_to_equity",
            "fcf_margin_pct",
            "revenue_growth_5y_pct",
            "eps_growth_5y_pct",
            *DCF_INPUT_COLUMNS,
            "beta",
            "price",
            "week_52_high",
            "week_52_low",
            "revenue_growth_3y_pct",
            "eps_growth_3y_pct",
            "free_cash_flow_per_share",
            "revenue_per_share",
            "book_value_per_share",
            "tangible_book_value_per_share",
            "long_term_debt_to_equity",
            "asset_turnover",
            "eps_ttm",
            "net_income",
            "free_cash_flow",
            "fcf_growth_5y_pct",
            "net_income_growth_5y_pct",
            "return_cagr_5y_pct",
            "return_cagr_10y_pct",
            "return_cagr_15y_pct",
            "roa_5y_avg_pct",
            "roe_5y_avg_pct",
            "roic_5y_avg_pct",
            "shares_insiders_pct",
            "shares_insiders_percent",
            "industry",
            "short_pct",
            "rating",
            "pt_upside_pct",
            "cyclical_peak_risk",
            "valuation_triangulation",
            "valuation_upside_capped_pct",
            *VALUATION_COLUMNS,
            *FLAG_COLUMNS,
        ]
        select_sql = f"SELECT {', '.join(base_columns)} FROM stocks WHERE {where_sql}"  # nosec B608

        count_sql = f"SELECT COUNT(*) FROM stocks WHERE {where_sql}"  # nosec B608
        page_size = max(1, min(int(page_size), 100_000))

        # COUNT(*) and the page must see the same snapshot: one connection.
        with self._connect() as conn:
            total_matching = conn.execute(count_sql, params).fetchone()[0]

            total_pages = max(1, (total_matching + page_size - 1) // page_size)
            safe_page = max(1, min(int(page), total_pages))
            offset = (safe_page - 1) * page_size

            if sort_column and sort_column in numeric_columns:
                sort_dir = "ASC" if sort_ascending else "DESC"
                select_sql += f" ORDER BY {sort_column} {sort_dir} NULLS LAST"

            select_sql += " LIMIT ? OFFSET ?"
            query_params = [*params, page_size, offset]

            cur = conn.execute(select_sql, query_params)
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]

        return StockQueryResult(rows, total_pages, total_matching, warnings=warnings)

    def save_stock(self, symbol: str, data: dict[str, Any]) -> None:
        """Upsert a stock's metrics."""
        with self._connect() as conn:
            self._upsert_stock(conn, {**data, "symbol": symbol})
            conn.commit()

    def replace_stocks(self, rows: list[dict[str, Any]]) -> None:
        """Atomically replace the screener universe with a fresh snapshot."""
        now = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM stocks")
            conn.execute("DELETE FROM sync_status WHERE sync_type='fundamentals'")
            for row in rows:
                self._upsert_stock(conn, row)
                conn.execute(
                    """INSERT INTO sync_status
                       (symbol, sync_type, status, error, last_attempt, attempts, next_retry_at)
                       VALUES (?, 'fundamentals', 'success', NULL, ?, 0, NULL)""",
                    (row["symbol"], now),
                )
            conn.commit()

    @staticmethod
    def _upsert_stock(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
        now = time.time()
        fields = []
        values = []
        fields_set = []

        for f in STOCK_FIELDS:
            if f in data and data.get(f) is not None:
                fields.append(f)
                values.append(data[f])
                fields_set.append(f"{f}=excluded.{f}")

        fields.append("updated_at")
        values.append(now)
        fields_set.append("updated_at=excluded.updated_at")

        sql = (
            f"INSERT INTO stocks ({', '.join(fields)}) "  # nosec B608
            f"VALUES ({', '.join(['?'] * len(values))}) "  # nosec B608
            f"ON CONFLICT(symbol) DO UPDATE SET {', '.join(fields_set)}"  # nosec B608
        )
        conn.execute(sql, values)

    def get_unique_values(self, column: str) -> list[str]:
        """Get unique values for an enum column."""
        allowed = {"exchange", "type", "currency", "mic", "valuation_triangulation"}
        if column not in allowed:
            return []

        with self._connect() as conn:
            query = (
                f"SELECT DISTINCT {column} FROM stocks "  # nosec B608
                f"WHERE {column} IS NOT NULL ORDER BY {column}"  # nosec B608
            )
            rows = conn.execute(query).fetchall()
        return [r[0] for r in rows]
