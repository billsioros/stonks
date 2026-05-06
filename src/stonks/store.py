"""SQLiteStore — persists saved screens and watchlists."""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from stonks.config import DB_PATH


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
                    PRIMARY KEY (symbol, sync_type)
                )
            """)
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
                    industry TEXT,
                    short_pct REAL,
                    rating TEXT,
                    pt_upside_pct REAL,
                    updated_at REAL
                )
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

    # ── Sync Status ──────────────────────────────────────────────────

    def update_sync_status(
        self, symbol: str, sync_type: str, status: str, error: str | None = None
    ) -> None:
        """Update the sync status for a symbol."""
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO sync_status (symbol, sync_type, status, error, last_attempt)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(symbol, sync_type) DO UPDATE SET
                     status=excluded.status,
                     error=excluded.error,
                     last_attempt=excluded.last_attempt
                """,
                (symbol, sync_type, status, error, now),
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

            success_basic = conn.execute(
                "SELECT COUNT(*) FROM sync_status WHERE status='success' AND sync_type='basic'"
            ).fetchone()[0]
            success_candles = conn.execute(
                "SELECT COUNT(*) FROM sync_status WHERE status='success' AND sync_type='candles'"
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM sync_status WHERE status='failed'"
            ).fetchone()[0]
            last_run = conn.execute(
                "SELECT MAX(last_attempt) FROM sync_status"
            ).fetchone()[0]

        return {
            "total_symbols": total_universe,
            "success_count": success_basic,
            "candles_count": success_candles,
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

    # ── Stocks ────────────────────────────────────────────────────────

    def get_stocks(
        self,
        filters: dict[str, Any] | None = None,
        search_query: str = "",
        sort_column: str | None = None,
        sort_ascending: bool = True,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[dict[str, Any]], int, int]:
        """Query stocks with filters, search, sort, pagination at DB level.

        Returns:
            Tuple of (rows, total_pages, total_matching).
        """
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
        }
        enum_columns = {"exchange", "type", "currency", "mic"}

        if filters:
            for col, spec in filters.items():
                if col in numeric_columns:
                    if "min" in spec and spec["min"] is not None:
                        where_clauses.append(f"{col} >= ?")
                        params.append(spec["min"])
                    if "max" in spec and spec["max"] is not None:
                        where_clauses.append(f"{col} <= ?")
                        params.append(spec["max"])
                elif col in enum_columns and "values" in spec and spec["values"]:
                    placeholders = ",".join(["?"] * len(spec["values"]))
                    where_clauses.append(f"{col} IN ({placeholders})")
                    params.extend(spec["values"])

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
            "industry",
            "short_pct",
            "rating",
            "pt_upside_pct",
        ]
        select_sql = f"SELECT {', '.join(base_columns)} FROM stocks WHERE {where_sql}"

        count_sql = f"SELECT COUNT(*) FROM stocks WHERE {where_sql}"
        with self._connect() as conn:
            total_matching = conn.execute(count_sql, params).fetchone()[0]

        total_pages = max(1, (total_matching + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size

        if sort_column and sort_column in numeric_columns:
            sort_dir = "ASC" if sort_ascending else "DESC"
            select_sql += f" ORDER BY {sort_column} {sort_dir} NULLS LAST"

        select_sql += f" LIMIT {page_size} OFFSET {offset}"

        rows: list[dict[str, Any]] = []
        with self._connect() as conn:
            cur = conn.execute(select_sql, params)
            cols = [c[0] for c in cur.description]
            for row in cur.fetchall():
                rows.append(dict(zip(cols, row)))

        return rows, total_pages, total_matching

    def save_stock(self, symbol: str, data: dict[str, Any]) -> None:
        """Upsert a stock's metrics."""
        now = time.time()

        all_fields = [
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
            "industry",
            "short_pct",
            "rating",
            "pt_upside_pct",
        ]

        fields = []
        values = []
        fields_set = []

        for f in all_fields:
            if f in data and data.get(f) is not None:
                fields.append(f)
                values.append(data[f])
                fields_set.append(f"{f}=excluded.{f}")

        fields.append("updated_at")
        values.append(now)
        fields_set.append("updated_at=excluded.updated_at")

        sql = f"""INSERT INTO stocks ({", ".join(fields)})
                  VALUES ({", ".join(["?"] * len(values))})
                  ON CONFLICT(symbol) DO UPDATE SET {", ".join(fields_set)}"""

        with self._connect() as conn:
            conn.execute(sql, values)
            conn.commit()

    def get_unique_values(self, column: str) -> list[str]:
        """Get unique values for an enum column."""
        allowed = {"exchange", "type", "currency", "mic"}
        if column not in allowed:
            return []

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT {column} FROM stocks WHERE {column} IS NOT NULL ORDER BY {column}"
            ).fetchall()
        return [r[0] for r in rows]

    def get_stock_count(self) -> int:
        """Get total count of stocks in DB."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM stocks").fetchone()
        return row[0] if row else 0
