"""Tests for the SQLiteStore module."""

import sqlite3
from pathlib import Path

import pytest

import stonks.store as store_module
from stonks.store import SQLiteStore


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(db_path=tmp_path / "test.db")


def test_is_stock_row_accepts_missing_type_and_rejects_funds() -> None:
    assert store_module.is_stock_row({"type": None}) is True
    assert store_module.is_stock_row({"type": "  "}) is True
    assert store_module.is_stock_row({"type": "Common Stock"}) is True
    assert store_module.is_stock_row({"type": "ETF"}) is False
    assert store_module.is_stock_row({"type": "Fund"}) is False


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

    def test_get_watchlist_rows_joins_stored_metrics(self, store: SQLiteStore) -> None:
        store.replace_stocks(
            [
                {"symbol": "AAPL", "industry": "Technology", "market_cap": 100.0},
                {"symbol": "XOM", "industry": "Energy", "market_cap": 300.0},
            ]
        )
        store.add_to_watchlist("AAPL")
        store.add_to_watchlist("XOM")

        rows = store.get_watchlist_rows()

        assert [row["symbol"] for row in rows] == ["AAPL", "XOM"]
        assert rows[0]["industry"] == "Technology"
        assert rows[1]["market_cap"] == 300.0

    def test_get_stock_symbols_lists_the_current_screener_universe(
        self, store: SQLiteStore
    ) -> None:
        store.replace_stocks(
            [
                {"symbol": "ZZZ", "description": "Zeta"},
                {"symbol": "AAA", "description": "Alpha"},
            ]
        )

        assert store.get_stock_symbols() == ["AAA", "ZZZ"]
        assert store.get_stock_symbols(filters={"symbol": {"values": ["AAA"]}}) == [
            "AAA"
        ]
        assert store.get_stock_symbols(search_query="zeta") == ["ZZZ"]

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

    # ── Positions ────────────────────────────────────────────────

    def test_get_positions_orders_lots_and_keeps_them_separate(
        self, store: SQLiteStore
    ) -> None:
        store.add_position("googl", 5, 100.0, "usd")
        store.add_position("CROX", 2, 50.0, "USD")
        store.add_position("GOOGL", 3, 120.0, "EUR")

        rows = store.get_positions()

        assert set(rows[0]) == {
            "id",
            "symbol",
            "quantity",
            "price",
            "currency",
            "added_at",
            "notes",
        }
        assert [(row["symbol"], row["quantity"], row["currency"]) for row in rows] == [
            ("CROX", 2.0, "USD"),
            ("GOOGL", 5.0, "USD"),
            ("GOOGL", 3.0, "EUR"),
        ]
        assert store.get_position_symbols() == ["CROX", "GOOGL"]

    def test_delete_position_removes_only_one_lot(self, store: SQLiteStore) -> None:
        store.add_position("AAA", 1, 10.0)
        store.add_position("AAA", 2, 12.0)
        first_id = store.get_positions()[0]["id"]
        store.delete_position(first_id)
        assert [row["quantity"] for row in store.get_positions()] == [2.0]

    def test_add_position_rejects_invalid_values(self, store: SQLiteStore) -> None:
        with pytest.raises(ValueError):
            store.add_position("", 1, 10.0)
        with pytest.raises(ValueError):
            store.add_position("AAA", 0, 10.0)
        with pytest.raises(ValueError):
            store.add_position("AAA", 1, -1.0)
        with pytest.raises(ValueError):
            store.add_position("AAA", float("nan"), 10.0)
        with pytest.raises(ValueError):
            store.add_position("AAA", 1, 10.0, "GBP")
        with pytest.raises(ValueError):
            store.add_position("AAA", 1, 10.0, "")

    def test_add_position_normalizes_lowercase_currency(
        self, store: SQLiteStore
    ) -> None:
        store.add_position("AAA", 1, 10.0, "usd")

        assert store.get_positions()[0]["currency"] == "USD"

    def test_positions_schema_rejects_unsupported_currency(
        self, store: SQLiteStore
    ) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            with store._connect() as conn:
                conn.execute(
                    """INSERT INTO positions
                       (symbol, quantity, price, currency, added_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    ("AAA", 1.0, 10.0, "GBP", 0.0),
                )

    def test_get_monitored_symbols_unions_watchlist_and_positions(
        self, store: SQLiteStore
    ) -> None:
        store.add_to_watchlist("WATCH")
        store.add_to_watchlist("BOTH")
        store.add_position("BOTH", 1, 10.0)
        store.add_position("HELD", 2, 20.0)
        assert store.get_monitored_symbols() == ["BOTH", "HELD", "WATCH"]


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


def test_cache_roundtrip(store: SQLiteStore) -> None:
    store.cache_set("sym:NVDA:overview:-:annual", {"a": [1, 2]}, ttl_seconds=60)
    assert store.cache_get("sym:NVDA:overview:-:annual") == {"a": [1, 2]}


def test_cache_missing_returns_none(store: SQLiteStore) -> None:
    assert store.cache_get("nope") is None


def test_cache_expired_returns_none(store: SQLiteStore) -> None:
    store.cache_set("k", {"a": 1}, ttl_seconds=-1)
    assert store.cache_get("k") is None


def test_cache_delete_removes_entry(store: SQLiteStore) -> None:
    store.cache_set("k", {"a": 1}, ttl_seconds=60)
    store.cache_delete("k")
    assert store.cache_get("k") is None


def test_cache_overwrite_replaces_value(store: SQLiteStore) -> None:
    store.cache_set("k", {"a": 1}, ttl_seconds=60)
    store.cache_set("k", {"a": 2}, ttl_seconds=60)
    assert store.cache_get("k") == {"a": 2}


def test_add_alert_is_idempotent(store: SQLiteStore) -> None:
    assert (
        store.add_alert("NVDA", "pe_drop", "good", "P/E down 20%", None, "k1") is True
    )
    assert (
        store.add_alert("NVDA", "pe_drop", "good", "P/E down 20%", None, "k1") is False
    )
    assert len(store.get_alerts()) == 1


def test_get_alerts_unread_only_and_newest_first(store: SQLiteStore) -> None:
    store.add_alert("AAA", "big_move", "warn", "moved", None, "a1")
    store.add_alert("BBB", "off_high", "good", "cheap", None, "b1")
    alerts = store.get_alerts()
    assert [a["symbol"] for a in alerts] == ["BBB", "AAA"]
    store.mark_alerts_seen([alerts[0]["id"]])
    assert [a["symbol"] for a in store.get_alerts()] == ["AAA"]
    assert len(store.get_alerts(unread_only=False)) == 2


def test_get_alerts_filters_by_symbol(store: SQLiteStore) -> None:
    store.add_alert("AAA", "off_high", "good", "cheap", None, "a1")
    store.add_alert("BBB", "off_high", "good", "cheap", None, "b1")
    assert [a["symbol"] for a in store.get_alerts(symbol="AAA")] == ["AAA"]


def test_alert_row_exposes_all_columns(store: SQLiteStore) -> None:
    store.add_alert("AAA", "off_high", "good", "cheap", "100 vs 200", "a1")
    alert = store.get_alerts()[0]
    assert alert["detail"] == "100 vs 200"
    assert alert["dedupe_key"] == "a1"
    assert alert["created_at"] > 0
    assert alert["seen_at"] is None


def test_count_unread_and_mark_read(store: SQLiteStore) -> None:
    store.add_alert("AAA", "off_high", "good", "cheap", None, "a1")
    store.add_alert("BBB", "off_high", "good", "cheap", None, "b1")
    assert store.count_unread_alerts() == 2
    store.mark_alerts_seen([a["id"] for a in store.get_alerts()])
    assert store.count_unread_alerts() == 0


def test_mark_alerts_seen_ignores_empty_list(store: SQLiteStore) -> None:
    store.add_alert("AAA", "off_high", "good", "cheap", None, "a1")
    store.mark_alerts_seen([])
    assert store.count_unread_alerts() == 1


def test_prune_alerts_drops_old_rows(store: SQLiteStore) -> None:
    store.add_alert("OLD", "off_high", "good", "cheap", None, "o1")
    with store._connect() as conn:
        conn.execute("UPDATE alerts SET created_at = 0")
        conn.commit()
    store.add_alert("NEW", "off_high", "good", "cheap", None, "n1")
    assert store.prune_alerts(14) == 1
    assert [a["symbol"] for a in store.get_alerts(unread_only=False)] == ["NEW"]


def test_unread_alert_counts_groups_by_symbol(store: SQLiteStore) -> None:
    store.add_alert("AAA", "off_high", "good", "cheap", None, "a1")
    store.add_alert("AAA", "big_move", "warn", "moved", None, "a2")
    store.add_alert("BBB", "off_high", "good", "cheap", None, "b1")
    store.mark_alerts_seen([store.get_alerts(symbol="BBB")[0]["id"]])

    assert store.unread_alert_counts() == {"AAA": 2}


def test_schema_migration_adds_side_by_side_columns(tmp_path) -> None:
    db_path = tmp_path / "test_migration.db"
    store = SQLiteStore(db_path=db_path)
    with store._connect() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(stocks)")}
    assert "shares_insiders_percent" in cols
    assert "cyclical_peak_risk" in cols
    assert "valuation_triangulation" in cols
    assert "valuation_upside_capped_pct" in cols


def test_startup_backfill_populates_shares_insiders_percent(tmp_path) -> None:
    db_path = tmp_path / "test_backfill.db"
    store = SQLiteStore(db_path=db_path)
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO stocks (symbol, shares_insiders_pct) VALUES (?, ?)",
            ("TEST", 0.05),
        )
        conn.commit()
    # Re-instantiating triggers startup migration/backfill
    store._migrate_schema(store._connect())
    with store._connect() as conn:
        row = conn.execute(
            "SELECT shares_insiders_pct, shares_insiders_percent FROM stocks WHERE symbol='TEST'"
        ).fetchone()
    assert row[0] == 0.05
    assert row[1] == 5.0


def test_get_stocks_returns_stock_query_result_tuple(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.save_stock("AAPL", {"market_cap": 3000.0})
    result = store.get_stocks()
    # Verifies backwards compatibility as a 3-tuple
    rows, pages, total = result
    assert len(rows) == 1
    assert pages == 1
    assert total == 1
    assert hasattr(result, "warnings")
    assert isinstance(result.warnings, list)


def test_get_stocks_handles_zero_and_negative_page_size(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.save_stock("AAPL", {"market_cap": 3000.0})
    rows, pages, _total = store.get_stocks(page_size=0)
    assert len(rows) == 1
    assert pages == 1
    rows_neg, pages_neg, _total_neg = store.get_stocks(page_size=-10)
    assert len(rows_neg) == 1
    assert pages_neg == 1


def test_unknown_filter_column_records_warning_and_skips(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.save_stock("AAPL", {"market_cap": 3000.0})
    result = store.get_stocks(filters={"non_existent_column": {"min": 10}})
    _rows, _, total = result
    assert total == 1
    assert any("non_existent_column" in w for w in result.warnings)


def test_empty_enum_values_matches_zero_rows(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.save_stock("AAPL", {"exchange": "NMS"})
    result = store.get_stocks(filters={"symbol": {"values": []}})
    rows, _, total = result
    assert total == 0
    assert len(rows) == 0


def test_inverted_bounds_records_warning_and_matches_nothing(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.save_stock("AAPL", {"pe_ratio": 25.0})
    result = store.get_stocks(filters={"pe_ratio": {"min": 50, "max": 10}})
    _rows, _, total = result
    assert total == 0
    assert any("min" in w and "max" in w for w in result.warnings)


def test_non_finite_numeric_bounds_ignored_with_warning(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.save_stock("AAPL", {"pe_ratio": 25.0})
    result = store.get_stocks(filters={"pe_ratio": {"min": float("nan")}})
    _rows, _, total = result
    assert total == 1
    assert any("non-finite" in w.lower() for w in result.warnings)


def test_all_filter_and_sort_columns_exist_in_schema(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    from stonks.config import ENUM_FILTER_COLUMNS, NUMERIC_FILTER_COLUMNS

    with store._connect() as conn:
        schema_cols = {row[1] for row in conn.execute("PRAGMA table_info(stocks)")}

    assert set(NUMERIC_FILTER_COLUMNS) <= schema_cols
    assert set(ENUM_FILTER_COLUMNS) <= schema_cols
