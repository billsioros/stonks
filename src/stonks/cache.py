"""Disk-based JSON cache with TTL support."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from stonks.config import CACHE_DIR


class LocalCache:
    """Simple file-system cache keyed by a string, storing JSON-serialisable data."""

    def __init__(self, cache_dir: Path = CACHE_DIR) -> None:
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _key_path(self, key: str) -> Path:
        """Hash the key to get a safe filename."""
        h = hashlib.sha256(key.encode()).hexdigest()[:16]
        safe = key.replace("/", "_").replace(":", "_")[:60]
        return self._cache_dir / f"{safe}_{h}.json"

    def get(self, key: str, ttl: int | None = None) -> Any | None:
        """Return cached value or None if miss / expired.

        Args:
            key: Cache key string.
            ttl: Time-to-live in seconds. None = never expire.
        """
        path = self._key_path(key)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

        if ttl is not None:
            stored_at = data.get("_ts", 0)
            if time.time() - stored_at > ttl:
                return None

        return data.get("value")

    def set(self, key: str, value: Any) -> None:
        """Store a value in the cache."""
        path = self._key_path(key)
        payload = {"_ts": time.time(), "value": value}
        path.write_text(json.dumps(payload, default=str))

    def clear(self) -> None:
        """Remove all cache files."""
        for f in self._cache_dir.glob("*.json"):
            f.unlink(missing_ok=True)

    def clear_key(self, key: str) -> None:
        """Remove a specific cache entry."""
        path = self._key_path(key)
        path.unlink(missing_ok=True)
