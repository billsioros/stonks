"""AppTest coverage for the watchlist alert banner, badge and marker column."""

import pytest
from streamlit.testing.v1 import AppTest

from stonks.store import SQLiteStore

TEST_KEY = "ZZZT:off_high:ui-test"
TEST_SYMBOL = "ZZZT"


def _app() -> AppTest:
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()
    return at


def _seed_alert() -> SQLiteStore:
    store = SQLiteStore()
    store.add_alert(
        TEST_SYMBOL,
        "off_high",
        "good",
        "Trading 21% below its 52-week high",
        "159.00 vs high 200.00",
        TEST_KEY,
    )
    return store


def _cleanup(store: SQLiteStore) -> None:
    with store._connect() as conn:
        conn.execute("DELETE FROM alerts WHERE dedupe_key = ?", (TEST_KEY,))
        conn.commit()


def test_banner_is_hidden_when_everything_is_read() -> None:
    store = SQLiteStore()
    if store.count_unread_alerts():
        pytest.skip("the local database already holds unread alerts")
    at = _app()
    assert not [item for item in at.info if "unread alert" in str(item.value)]
    assert not [button for button in at.button if button.label == "Mark all read"]


def test_banner_lists_alert_and_marks_all_read() -> None:
    store = _seed_alert()
    try:
        at = _app()
        assert any("unread alert" in str(item.value) for item in at.info)
        assert any("below its 52-week high" in str(md.value) for md in at.markdown)

        next(b for b in at.button if b.label == "Mark all read").click().run()

        assert store.count_unread_alerts() == 0
        assert not [b for b in at.button if b.label == "Mark all read"]
    finally:
        _cleanup(store)


def test_watchlist_tab_badge_counts_unread_alerts() -> None:
    store = _seed_alert()
    try:
        expected = store.count_unread_alerts()
        at = _app()
        assert f"⭐ Watchlist ({expected})" in [tab.label for tab in at.tabs]
    finally:
        _cleanup(store)


def test_watchlist_table_marks_symbols_with_alerts() -> None:
    store = SQLiteStore()
    store.save_stock(TEST_SYMBOL, {"description": "Test Co", "price": 10.0})
    store.add_to_watchlist(TEST_SYMBOL)
    store.add_alert(TEST_SYMBOL, "off_high", "good", "cheap", None, TEST_KEY)
    try:
        at = _app()
        frames = [frame.value for frame in at.dataframe]
        marked = [f for f in frames if "Alerts" in list(f.columns)]
        assert marked, "the watchlist frame should carry an Alerts column"
        row = marked[0].loc[marked[0]["Symbol"] == TEST_SYMBOL]
        assert row["Alerts"].tolist() == ["1"]
    finally:
        with store._connect() as conn:
            conn.execute("DELETE FROM stocks WHERE symbol = ?", (TEST_SYMBOL,))
            conn.execute("DELETE FROM watchlist WHERE symbol = ?", (TEST_SYMBOL,))
            conn.commit()
        _cleanup(store)
