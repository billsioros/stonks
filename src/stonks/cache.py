"""SQLite-based Key-Value cache with TTL support."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from stonks.config import DB_PATH

logger = logging.getLogger(__name__)


class LocalCache:
    """SQLite-based cache keyed by a string, storing JSON-serialisable data."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kv_cache (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    expires_at REAL
                )
            """)
            conn.commit()

    def get(self, key: str, ttl: int | None = None) -> Any | None:
        """Return cached value or None if miss / expired."""
        now = time.time()
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT value, expires_at FROM kv_cache WHERE key = ?", (key,)
                ).fetchone()
        except sqlite3.Error as e:
            logger.error("Cache get error: %s", e)
            return None

        if not row:
            return None

        val_json, expires_at = row
        if ttl is not None or expires_at is not None:
            # We use the most restrictive of the two
            exp = (
                min(expires_at, now + ttl)
                if expires_at is not None and ttl is not None
                else (expires_at if expires_at is not None else (now + ttl))
            )
            if now > exp:
                return None

        try:
            return json.loads(val_json)
        except json.JSONDecodeError:
            return None

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Bulk retrieval of multiple cache keys."""
        if not keys:
            return {}

        now = time.time()
        results = {}

        # Handle SQLite parameter limit (usually ~999)
        batch_size = 900
        for i in range(0, len(keys), batch_size):
            batch = keys[i : i + batch_size]
            placeholders = ",".join(["?"] * len(batch))

            try:
                with sqlite3.connect(self._db_path) as conn:
                    rows = conn.execute(
                        f"SELECT key, value, expires_at FROM kv_cache WHERE key IN ({placeholders})",  # nosec B608
                        batch,
                    ).fetchall()

                for key, val_json, expires_at in rows:
                    if expires_at is not None and now > expires_at:
                        continue
                    try:
                        results[key] = json.loads(val_json)
                    except json.JSONDecodeError:
                        continue
            except sqlite3.Error as e:
                logger.error("Cache get_many error: %s", e)
                continue

        return results

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value in the cache."""
        expires_at = (time.time() + ttl) if ttl is not None else None
        try:
            val_json = json.dumps(value, default=str)
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO kv_cache (key, value, expires_at) VALUES (?, ?, ?)",
                    (key, val_json, expires_at),
                )
                conn.commit()
        except (sqlite3.Error, TypeError) as e:
            logger.error("Cache set error for key %s: %s", key, e)

    def clear(self) -> None:
        """Remove all cache entries."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM kv_cache")
                conn.commit()
        except sqlite3.Error as e:
            logger.error("Cache clear error: %s", e)
