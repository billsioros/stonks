"""Tests for the LocalCache module."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stonks.cache import LocalCache


@pytest.fixture
def cache(tmp_path: Path) -> LocalCache:
    """Create a cache instance with a temporary database file."""
    return LocalCache(db_path=tmp_path / "cache.db")


class TestLocalCache:
    def test_set_and_get(self, cache: LocalCache) -> None:
        cache.set("test_key", {"foo": "bar"})
        result = cache.get("test_key")
        assert result == {"foo": "bar"}

    def test_get_missing_key(self, cache: LocalCache) -> None:
        result = cache.get("nonexistent")
        assert result is None

    def test_ttl_not_expired(self, cache: LocalCache) -> None:
        cache.set("key", "value", ttl=3600)
        result = cache.get("key")
        assert result == "value"

    def test_ttl_expired(self, cache: LocalCache) -> None:
        cache.set("key", "value", ttl=3600)

        # Manually backdate the timestamp in the database
        with sqlite3.connect(cache._db_path) as conn:
            conn.execute(
                "UPDATE kv_cache SET expires_at = ? WHERE key = ?",
                (time.time() - 10, "key"),
            )
            conn.commit()

        # Try to get it with a long enough TTL that it would be expired
        result = cache.get("key", ttl=5)
        assert result is None

    def test_clear(self, cache: LocalCache) -> None:
        cache.set("key1", "val1")
        cache.set("key2", "val2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_delete(self, cache: LocalCache) -> None:
        cache.set("key1", "val1")
        cache.set("key2", "val2")
        cache.delete("key1")
        assert cache.get("key1") is None
        assert cache.get("key2") == "val2"

    def test_delete_expired(self, cache: LocalCache) -> None:
        cache.set("expired", "val1", ttl=-10)  # Already expired
        cache.set("valid", "val2", ttl=3600)

        cache.delete_expired()

        assert cache.get("expired") is None
        assert cache.get("valid") == "val2"

    def test_stores_various_types(self, cache: LocalCache) -> None:
        cache.set("str", "hello")
        cache.set("int", 42)
        cache.set("list", [1, 2, 3])
        cache.set("nested", {"a": {"b": [1, 2]}})

        assert cache.get("str") == "hello"
        assert cache.get("int") == 42
        assert cache.get("list") == [1, 2, 3]
        assert cache.get("nested") == {"a": {"b": [1, 2]}}

    def test_get_many(self, cache: LocalCache) -> None:
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.set("k3", "v3", ttl=-10)  # Expired

        results = cache.get_many(["k1", "k2", "k3", "k4"])
        assert results == {"k1": "v1", "k2": "v2"}

    def test_get_db_error(self, cache: LocalCache) -> None:
        with patch("sqlite3.connect") as mock_connect:
            mock_connect.side_effect = sqlite3.Error("Connection error")
            assert cache.get("key") is None

    def test_set_db_error(self, cache: LocalCache) -> None:
        with patch("sqlite3.connect") as mock_connect:
            mock_connect.side_effect = sqlite3.Error("Connection error")
            # Should not raise
            cache.set("key", "val")

    def test_get_invalid_json(self, cache: LocalCache) -> None:
        # Manually insert invalid JSON
        with sqlite3.connect(cache._db_path) as conn:
            conn.execute(
                "INSERT INTO kv_cache (key, value) VALUES (?, ?)",
                ("bad_json", "{invalid"),
            )
            conn.commit()

        assert cache.get("bad_json") is None

    def test_get_many_invalid_json(self, cache: LocalCache) -> None:
        cache.set("good", "val")
        with sqlite3.connect(cache._db_path) as conn:
            conn.execute(
                "INSERT INTO kv_cache (key, value) VALUES (?, ?)", ("bad", "{invalid")
            )
            conn.commit()

        results = cache.get_many(["good", "bad"])
        assert results == {"good": "val"}
