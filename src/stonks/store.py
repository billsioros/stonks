"""SQLiteStore — persists saved screens and watchlists."""

from __future__ import annotations

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

    def get_screen(self, name: str) -> dict[str, Any] | None:
        """Retrieve a specific saved screen by name."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, filters, view_preset, sort_column, sort_ascending, created_at, updated_at FROM saved_screens WHERE name=?",
                (name,),
            ).fetchone()

        if not row:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "filters": json.loads(row[2]),
            "view_preset": row[3],
            "sort_column": row[4],
            "sort_ascending": bool(row[5]),
            "created_at": row[6],
            "updated_at": row[7],
        }

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

    def is_in_watchlist(self, symbol: str) -> bool:
        """Check if a symbol is in the watchlist."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM watchlist WHERE symbol=?", (symbol,)
            ).fetchone()
        return row is not None

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

    def get_failed_symbols(self, sync_type: str) -> list[str]:
        """Return symbols that failed the last sync attempt."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT symbol FROM sync_status WHERE sync_type=? AND status='failed'",
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
