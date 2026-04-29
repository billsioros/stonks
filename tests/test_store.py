"""Tests for the SQLiteStore module."""

from pathlib import Path

import pytest

from stonks.store import SQLiteStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(db_path=tmp_path / "test.db")


class TestSQLiteStore:
    # ── Saved Screens ────────────────────────────────────────────

    def test_save_and_list_screens(self, store: SQLiteStore) -> None:
        store.save_screen("Test Screen", {"pe_ratio": {"max": 20}})
        screens = store.list_screens()
        assert len(screens) == 1
        assert screens[0]["name"] == "Test Screen"
        assert screens[0]["filters"] == {"pe_ratio": {"max": 20}}

    def test_save_screen_upsert(self, store: SQLiteStore) -> None:
        store.save_screen("S1", {"pe_ratio": {"min": 10}})
        store.save_screen("S1", {"pe_ratio": {"min": 20}})
        screens = store.list_screens()
        assert len(screens) == 1
        assert screens[0]["filters"] == {"pe_ratio": {"min": 20}}

    def test_delete_screen(self, store: SQLiteStore) -> None:
        store.save_screen("S1", {})
        store.delete_screen("S1")
        assert store.list_screens() == []

    # ── Watchlist ────────────────────────────────────────────────

    def test_add_to_watchlist(self, store: SQLiteStore) -> None:
        store.add_to_watchlist("AAPL")
        wl = store.get_watchlist()
        assert len(wl) == 1
        assert wl[0]["symbol"] == "AAPL"

    def test_add_duplicate_to_watchlist(self, store: SQLiteStore) -> None:
        store.add_to_watchlist("AAPL", notes="first")
        store.add_to_watchlist("AAPL", notes="updated")
        wl = store.get_watchlist()
        assert len(wl) == 1
        assert wl[0]["notes"] == "updated"

    def test_remove_from_watchlist(self, store: SQLiteStore) -> None:
        store.add_to_watchlist("AAPL")
        store.add_to_watchlist("GOOGL")
        store.remove_from_watchlist("AAPL")
        symbols = store.get_watchlist_symbols()
        assert symbols == ["GOOGL"]

    def test_get_watchlist_symbols(self, store: SQLiteStore) -> None:
        store.add_to_watchlist("MSFT")
        store.add_to_watchlist("AAPL")
        symbols = store.get_watchlist_symbols()
        assert "MSFT" in symbols
        assert "AAPL" in symbols

    # ── Sync Status ──────────────────────────────────────────────

    def test_sync_status(self, store: SQLiteStore) -> None:
        store.update_sync_status("AAPL", "basic", "success")
        store.update_sync_status("GOOGL", "basic", "failed", error="429")

        info = store.get_last_sync_info()
        assert info["total_symbols"] == 2
        assert info["success_count"] == 1
        assert info["failed_count"] == 1

    def test_last_sync_info_with_metadata(self, store: SQLiteStore) -> None:
        store.save_metadata("universe_size", 1000)
        store.update_sync_status("AAPL", "basic", "success")

        info = store.get_last_sync_info()
        assert info["total_symbols"] == 1000
        assert info["success_count"] == 1

    # ── New Sync Methods ──────────────────────────────────────────

    def test_get_synced_symbols(self, store: SQLiteStore) -> None:
        store.update_sync_status("AAPL", "basic", "success")
        store.update_sync_status("GOOGL", "basic", "success")
        store.update_sync_status("TSLA", "basic", "failed", error="429")

        synced = store.get_synced_symbols("basic")
        assert set(synced) == {"AAPL", "GOOGL"}
        assert "TSLA" not in synced

    def test_get_synced_symbols_empty(self, store: SQLiteStore) -> None:
        synced = store.get_synced_symbols("basic")
        assert synced == []

    def test_get_synced_symbols_different_types(self, store: SQLiteStore) -> None:
        store.update_sync_status("AAPL", "basic", "success")
        store.update_sync_status("AAPL", "candles", "success")

        basic_synced = store.get_synced_symbols("basic")
        candles_synced = store.get_synced_symbols("candles")
        assert basic_synced == ["AAPL"]
        assert candles_synced == ["AAPL"]

    def test_get_stale_symbols(self, store: SQLiteStore) -> None:
        import time

        # Symbol synced recently (should not be stale)
        store.update_sync_status("AAPL", "basic", "success")

        # Symbol synced 8 days ago (should be stale with 7 day threshold)
        old_time = time.time() - (8 * 24 * 3600)
        store.update_sync_status("GOOGL", "basic", "success")
        with store._connect() as conn:
            conn.execute(
                "UPDATE sync_status SET last_attempt = ? WHERE symbol = ? AND sync_type = ?",
                (old_time, "GOOGL", "basic"),
            )
            conn.commit()

        stale = store.get_stale_symbols("basic", stale_hours=24 * 7)
        assert "GOOGL" in stale
        assert "AAPL" not in stale

    def test_get_stale_symbols_failed_not_included(self, store: SQLiteStore) -> None:
        import time

        # Failed symbol (should not be in stale list)
        old_time = time.time() - (8 * 24 * 3600)
        store.update_sync_status("TSLA", "basic", "failed", error="429")
        with store._connect() as conn:
            conn.execute(
                "UPDATE sync_status SET last_attempt = ? WHERE symbol = ? AND sync_type = ?",
                (old_time, "TSLA", "basic"),
            )
            conn.commit()

        stale = store.get_stale_symbols("basic", stale_hours=24 * 7)
        assert "TSLA" not in stale

    def test_get_stale_symbols_custom_threshold(self, store: SQLiteStore) -> None:
        import time

        # Symbol synced 2 days ago
        old_time = time.time() - (2 * 24 * 3600)
        store.update_sync_status("AAPL", "basic", "success")
        with store._connect() as conn:
            conn.execute(
                "UPDATE sync_status SET last_attempt = ? WHERE symbol = ? AND sync_type = ?",
                (old_time, "AAPL", "basic"),
            )
            conn.commit()

        # With 1 day threshold, should be stale
        stale = store.get_stale_symbols("basic", stale_hours=24)
        assert "AAPL" in stale

        # With 7 day threshold, should not be stale
        stale = store.get_stale_symbols("basic", stale_hours=24 * 7)
        assert "AAPL" not in stale

    # ── Metadata ──────────────────────────────────────────────────

    def test_metadata(self, store: SQLiteStore) -> None:
        store.save_metadata("version", "1.0.0")
        assert store.get_metadata("version") == "1.0.0"
        assert store.get_metadata("no_such_key") is None

        store.save_metadata("version", "1.1.0")
        assert store.get_metadata("version") == "1.1.0"
