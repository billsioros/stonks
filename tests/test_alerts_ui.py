"""AppTest coverage for the watchlist alert banner, badge and marker column."""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from stonks import app
from stonks.store import SQLiteStore

TEST_KEY = "ZZZT:off_high:ui-test"
TEST_SYMBOL = "ZZZT"


@pytest.fixture(autouse=True)
def _clear_resource_cache_after_each_test() -> None:
    """Prevent a temp-DB AppTest from leaking its cached store into later tests."""
    yield
    st.cache_resource.clear()


def _app(
    db_path: Path, monkeypatch, *, session_state: dict[str, object] | None = None
) -> AppTest:
    real_init = SQLiteStore.__init__

    def _init(self, *args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(SQLiteStore, "__init__", _init)
    monkeypatch.setattr(app, "get_store", lambda: SQLiteStore(db_path=db_path))
    st.cache_resource.clear()
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    for key, value in {"active_filters": {}, **(session_state or {})}.items():
        at.session_state[key] = value
    at.run()
    return at


def _seed_alert(store: SQLiteStore) -> None:
    store.add_to_watchlist(TEST_SYMBOL)
    store.add_alert(
        TEST_SYMBOL,
        "off_high",
        "good",
        "Trading 21% below its 52-week high",
        "159.00 vs high 200.00",
        TEST_KEY,
    )


def test_banner_is_hidden_when_everything_is_read(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "stonks.db"
    at = _app(db_path, monkeypatch)

    assert not at.exception
    assert not [item for item in at.info if "unread alert" in str(item.value)]
    assert not [button for button in at.button if button.label == "Mark all read"]


def test_banner_lists_alert_and_marks_all_read(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "stonks.db"
    store = SQLiteStore(db_path=db_path)
    _seed_alert(store)

    at = _app(db_path, monkeypatch)

    assert not at.exception
    assert any("unread alert" in str(item.value) for item in at.info)
    assert any("below its 52-week high" in str(md.value) for md in at.markdown)

    next(b for b in at.button if b.label == "Mark all read").click().run()

    assert store.count_unread_alerts() == 0

    # AppTest keeps collapsed expander children from the previous run, so
    # use a fresh run to check that the alert controls are gone.
    at = _app(db_path, monkeypatch)
    assert not [b for b in at.button if b.label == "Mark all read"]


def test_watchlist_tab_label_has_no_alert_count(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "stonks.db"
    store = SQLiteStore(db_path=db_path)
    _seed_alert(store)

    at = _app(db_path, monkeypatch)

    assert not at.exception
    assert "⭐ Watchlist" in [tab.label for tab in at.tabs]
    assert not any("Watchlist (" in tab.label for tab in at.tabs)


def test_watchlist_table_marks_symbols_with_alerts(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "stonks.db"
    store = SQLiteStore(db_path=db_path)
    store.save_stock(TEST_SYMBOL, {"description": "Test Co", "price": 10.0})
    _seed_alert(store)

    at = _app(db_path, monkeypatch)

    assert not at.exception
    frames = [frame.value for frame in at.dataframe]
    marked = [f for f in frames if "Alerts" in list(f.columns)]
    assert marked, "the watchlist frame should carry an Alerts column"
    row = marked[0].loc[marked[0]["Symbol"] == TEST_SYMBOL]
    assert row["Alerts"].tolist() == ["1"]
