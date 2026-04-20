"""Tests for the LocalCache module."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from stonks.cache import LocalCache


@pytest.fixture
def cache(tmp_path: Path) -> LocalCache:
    """Create a cache instance with a temporary directory."""
    return LocalCache(cache_dir=tmp_path / "cache")


class TestLocalCache:
    def test_set_and_get(self, cache: LocalCache) -> None:
        cache.set("test_key", {"foo": "bar"})
        result = cache.get("test_key")
        assert result == {"foo": "bar"}

    def test_get_missing_key(self, cache: LocalCache) -> None:
        result = cache.get("nonexistent")
        assert result is None

    def test_ttl_not_expired(self, cache: LocalCache) -> None:
        cache.set("key", "value")
        result = cache.get("key", ttl=3600)
        assert result == "value"

    def test_ttl_expired(self, cache: LocalCache) -> None:
        cache.set("key", "value")
        # Manually backdate the timestamp
        path = cache._key_path("key")
        data = json.loads(path.read_text())
        data["_ts"] = time.time() - 7200  # 2 hours ago
        path.write_text(json.dumps(data))

        result = cache.get("key", ttl=3600)
        assert result is None

    def test_clear(self, cache: LocalCache) -> None:
        cache.set("key1", "val1")
        cache.set("key2", "val2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_clear_key(self, cache: LocalCache) -> None:
        cache.set("key1", "val1")
        cache.set("key2", "val2")
        cache.clear_key("key1")
        assert cache.get("key1") is None
        assert cache.get("key2") == "val2"

    def test_stores_various_types(self, cache: LocalCache) -> None:
        cache.set("str", "hello")
        cache.set("int", 42)
        cache.set("list", [1, 2, 3])
        cache.set("nested", {"a": {"b": [1, 2]}})

        assert cache.get("str") == "hello"
        assert cache.get("int") == 42
        assert cache.get("list") == [1, 2, 3]
        assert cache.get("nested") == {"a": {"b": [1, 2]}}
