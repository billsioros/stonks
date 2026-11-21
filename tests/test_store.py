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
        store.update_sync_status("AAPL", "fundamentals", "success")
        store.update_sync_status("GOOGL", "fundamentals", "failed", error="429")

        info = store.get_last_sync_info()
        assert info["total_symbols"] == 2
        assert info["success_count"] == 1
        assert info["failed_count"] == 1

    def test_last_sync_info_counts_fundamentals(self, store: SQLiteStore) -> None:
        store.update_sync_status("AAPL", "fundamentals", "success")
        store.update_sync_status("GOOGL", "fundamentals", "failed", error="429")

        info = store.get_last_sync_info()
        assert info["success_count"] == 1
        assert info["fundamentals_count"] == 1
        assert info["failed_count"] == 1

    def test_last_sync_info_with_metadata(self, store: SQLiteStore) -> None:
        store.save_metadata("universe_size", 1000)
        store.update_sync_status("AAPL", "fundamentals", "success")

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


def test_store_filters_sort_search_and_preserves_values(store: SQLiteStore) -> None:
    store.save_stock(
        "AAA",
        {
            "description": "Alpha",
            "exchange": "NYSE",
            "market_cap": 100.0,
            "pe_ratio": 10.0,
        },
    )
    store.save_stock(
        "BBB",
        {
            "description": "Beta",
            "exchange": "NASDAQ",
            "market_cap": 50.0,
            "pe_ratio": 20.0,
        },
    )
    store.save_stock(
        "CCC", {"description": "Null Cap", "exchange": "NYSE", "pe_ratio": 5.0}
    )

    rows, _, total = store.get_stocks(
        filters={"market_cap": {"min": 60}},
        sort_column="pe_ratio",
        sort_ascending=False,
    )
    assert total == 1
    assert [row["symbol"] for row in rows] == ["AAA"]

    rows, _, total = store.get_stocks(filters={"exchange": {"values": ["NASDAQ"]}})
    assert total == 1
    assert [row["symbol"] for row in rows] == ["BBB"]

    rows, _, total = store.get_stocks(filters={"symbol": {"values": ["CCC", "AAA"]}})
    assert total == 2
    assert sorted(row["symbol"] for row in rows) == ["AAA", "CCC"]

    rows, _, total = store.get_stocks(search_query="Alpha")
    assert total == 1
    assert rows[0]["symbol"] == "AAA"

    rows, total_pages, total = store.get_stocks(
        page=2, page_size=1, sort_column="symbol"
    )
    assert total == 3 and total_pages == 3
    assert rows[0]["symbol"] == "BBB"

    store.save_stock("AAA", {"pe_ratio": None, "market_cap": 120.0})
    row = store.get_stocks(search_query="Alpha")[0][0]
    assert row["pe_ratio"] == 10.0
    assert row["market_cap"] == 120.0


def test_replace_stocks_discards_stale_symbols_and_values(store: SQLiteStore) -> None:
    store.save_stock("OLD", {"roe_5y_avg_pct": 42.0})
    store.save_stock("UI", {"roe_5y_avg_pct": 47.28})
    store.update_sync_status("OLD", "fundamentals", "success")

    store.replace_stocks(
        [
            {"symbol": "NEW", "roe_5y_avg_pct": 12.0},
            {"symbol": "UI", "roe_5y_avg_pct": None},
        ]
    )

    assert [r["symbol"] for r in store.get_stocks(page_size=10)[0]] == ["NEW", "UI"]
    with store._connect() as conn:
        ui = conn.execute(
            "SELECT roe_5y_avg_pct FROM stocks WHERE symbol='UI'"
        ).fetchone()
        statuses = conn.execute(
            "SELECT symbol, status FROM sync_status WHERE sync_type='fundamentals'"
        ).fetchall()
    assert ui[0] is None
    assert [(r[0], r[1]) for r in statuses] == [("NEW", "success"), ("UI", "success")]
