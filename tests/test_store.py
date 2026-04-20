"""Tests for the SQLiteStore module."""

from __future__ import annotations

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

    def test_get_screen(self, store: SQLiteStore) -> None:
        store.save_screen("S1", {"roe_pct": {"min": 15}}, view_preset="Profitability")
        screen = store.get_screen("S1")
        assert screen is not None
        assert screen["view_preset"] == "Profitability"

    def test_get_screen_not_found(self, store: SQLiteStore) -> None:
        assert store.get_screen("NoSuchScreen") is None

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

    def test_is_in_watchlist(self, store: SQLiteStore) -> None:
        store.add_to_watchlist("AAPL")
        assert store.is_in_watchlist("AAPL") is True
        assert store.is_in_watchlist("GOOGL") is False

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

        failed = store.get_failed_symbols("basic")
        assert failed == ["GOOGL"]

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

    # ── Metadata ──────────────────────────────────────────────────

    def test_metadata(self, store: SQLiteStore) -> None:
        store.save_metadata("version", "1.0.0")
        assert store.get_metadata("version") == "1.0.0"
        assert store.get_metadata("no_such_key") is None

        store.save_metadata("version", "1.1.0")
        assert store.get_metadata("version") == "1.1.0"
