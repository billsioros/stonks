"""AppTest coverage for the watchlist's screener-style table and symbol editor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from stonks import app, config
from stonks.store import SQLiteStore


@pytest.fixture(autouse=True)
def _clear_resource_cache_after_each_test() -> None:
    yield
    st.cache_resource.clear()


def _stock(symbol: str, type_: str | None = "Stock") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "description": f"{symbol} Inc",
        "type": type_,
        "price": 100.0,
        "pe_ratio": 20.0,
        "pb_ratio": 2.0,
        "industry": "Tech",
    }


def _watchlist_panel(at: AppTest):
    return next(
        expander
        for expander in at.expander
        if any(text_input.placeholder == "AAPL" for text_input in expander.text_input)
    )


def _app_with_db(
    db_path: Path, monkeypatch, active_filters: dict | None = None
) -> AppTest:
    real_init = SQLiteStore.__init__

    def _init(self, *args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(SQLiteStore, "__init__", _init)
    monkeypatch.setattr(app, "get_store", lambda: SQLiteStore(db_path=db_path))
    st.cache_resource.clear()
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.session_state["active_filters"] = active_filters or {}
    at.run()
    return at


def test_watchlist_table_uses_the_screener_view_preset(tmp_path, monkeypatch) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.replace_stocks([_stock("AAA")])
    store.add_to_watchlist("AAA")

    at = _app_with_db(tmp_path / "test.db", monkeypatch)
    selector = next(s for s in at.selectbox if s.key == "watchlist_view_preset_select")

    assert selector.options == list(config.VIEW_PRESETS.keys())
    selector.set_value("Valuation").run()

    table = next(d for d in at.dataframe if "Alerts" in d.value.columns)
    assert "P/B" in table.value.columns
    assert "ROE %" not in table.value.columns


def test_watchlist_lists_symbols_with_edit_and_remove_actions(
    tmp_path, monkeypatch
) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.replace_stocks([_stock("AAA"), _stock("BBB")])
    store.add_to_watchlist("AAA")
    store.add_to_watchlist("BBB")

    at = _app_with_db(tmp_path / "test.db", monkeypatch)

    assert not at.exception
    assert any(b.key == "wl_edit_symbol_0" for b in at.button)
    assert any(b.key == "wl_delete_symbol_1" for b in at.button)


def test_watchlist_adds_a_stock_outside_the_active_screener(
    tmp_path, monkeypatch
) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.replace_stocks([_stock("AAA"), _stock("BBB")])
    store.add_to_watchlist("AAA")
    at = _app_with_db(
        tmp_path / "test.db",
        monkeypatch,
        active_filters={"symbol": {"values": ["AAA"]}},
    )

    panel = _watchlist_panel(at)
    panel.text_input[0].set_value("BBB")
    next(b for b in panel.button if b.label == "Add").click().run()

    assert not at.exception
    assert store.get_watchlist_symbols() == ["AAA", "BBB"]


def test_watchlist_hides_a_legacy_etf(tmp_path, monkeypatch) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.replace_stocks([_stock("AAA"), _stock("VUAA", "ETF")])
    store.add_to_watchlist("AAA")
    store.add_to_watchlist("VUAA")

    at = _app_with_db(tmp_path / "test.db", monkeypatch)

    assert not at.exception
    table = next(d for d in at.dataframe if "Alerts" in d.value.columns)
    assert "VUAA" not in table.value["Symbol"].tolist()
    assert not any(b.key == "wl_edit_symbol_1" for b in at.button)


def test_watchlist_rejects_an_etf(tmp_path, monkeypatch) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.replace_stocks([_stock("AAA"), _stock("VUAA", "ETF")])
    store.add_to_watchlist("AAA")
    at = _app_with_db(tmp_path / "test.db", monkeypatch)

    panel = _watchlist_panel(at)
    panel.text_input[0].set_value("VUAA")
    next(b for b in panel.button if b.label == "Add").click().run()

    assert not at.exception
    assert store.get_watchlist_symbols() == ["AAA"]
    assert any("stock" in str(w.value).lower() for w in at.warning)


def test_watchlist_edits_and_removes_a_symbol(tmp_path, monkeypatch) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.replace_stocks([_stock("AAA"), _stock("BBB")])
    store.add_to_watchlist("AAA")
    at = _app_with_db(tmp_path / "test.db", monkeypatch)

    next(b for b in at.button if b.key == "wl_edit_symbol_0").click().run()
    panel = _watchlist_panel(at)
    assert panel.text_input[0].value == "AAA"
    panel.text_input[0].set_value("BBB")
    next(b for b in panel.button if b.label == "Save changes").click().run()

    assert not at.exception
    assert store.get_watchlist_symbols() == ["BBB"]

    next(b for b in at.button if b.key == "wl_delete_symbol_0").click().run()

    assert not at.exception
    assert store.get_watchlist_symbols() == []
