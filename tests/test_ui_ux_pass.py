"""Regression tests for the viewport-height screener and compact UI pass."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from stonks import app, backtest_view, config
from stonks.backtest import simulate
from stonks.backtest_view import _RESULT_KEY
from stonks.store import SQLiteStore


@pytest.fixture(autouse=True)
def _clear_resource_cache_after_each_test() -> None:
    """Keep temp-DB AppTest runs from leaking a cached store into other tests."""
    yield
    st.cache_resource.clear()


def _app() -> AppTest:
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()
    return at


def _app_with_db(db_path: Path, monkeypatch) -> AppTest:
    real_init = SQLiteStore.__init__

    def _init(self, *args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(SQLiteStore, "__init__", _init)
    monkeypatch.setattr(app, "get_store", lambda: SQLiteStore(db_path=db_path))
    st.cache_resource.clear()
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()
    return at


def test_screener_defaults_to_a_viewport_sized_page() -> None:
    assert config.DEFAULT_PAGE_SIZE == 25
    assert config.DEFAULT_PAGE_SIZE in config.PAGE_SIZE_OPTIONS
    assert config.SCREENER_TABLE_MAX_HEIGHT == 480


def test_screener_table_height_never_exceeds_the_viewport_cap() -> None:
    assert app._screener_table_height(5) == 264
    assert app._screener_table_height(10) == config.SCREENER_TABLE_MAX_HEIGHT
    assert app._screener_table_height(100) == config.SCREENER_TABLE_MAX_HEIGHT


def test_popular_and_saved_screen_cards_share_one_compact_grid() -> None:
    assert app._screen_column_ratios(False) == [6, 1, 1]
    assert app._screen_column_ratios(True) == [6, 1, 1]


def test_sidebar_screen_cards_get_narrow_width_styling() -> None:
    at = _app()
    css = "\n".join(
        str(item.value) for item in at.markdown if "<style>" in str(item.value)
    )
    assert '[data-testid="stSidebar"] [class*="st-key-screen-"]' in css


def test_backtest_results_label_the_yearly_table() -> None:
    result = simulate(
        {
            "AAA": {
                "2024-01": 100.0,
                "2024-12": 110.0,
                "2025-01": 110.0,
                "2025-12": 130.0,
            }
        },
        {"AAA": 1.0},
        initial=1000.0,
    )
    result.update(
        {
            "symbols": ["AAA"],
            "weights": {"AAA": 100.0},
            "rebalance": "none",
            "allocation_mode": "percent",
        }
    )
    at = _app()
    at.session_state[_RESULT_KEY] = result
    at.run()

    assert not at.exception
    assert any("Annual returns" in str(item.value) for item in at.caption)


def test_layout_widgets_use_the_current_streamlit_width_api() -> None:
    assert "use_container_width" not in inspect.getsource(app)
    assert "use_container_width" not in inspect.getsource(backtest_view)


def test_notifications_promote_and_tag_watchlist_buy_opportunities(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "stonks.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks(
        [
            {
                "symbol": "WATCH",
                "description": "Watched company",
                "price": 101.0,
                "week_52_low": 100.0,
                "dcf_fair_value": None,
                "lynch_fair_value": None,
            },
            {
                "symbol": "OTHER",
                "description": "Below both estimates",
                "price": 101.0,
                "week_52_low": 100.0,
                "dcf_fair_value": 120.0,
                "lynch_fair_value": 130.0,
            },
        ]
    )
    store.add_to_watchlist("WATCH")

    at = _app_with_db(db_path, monkeypatch)
    assert not at.exception
    notification = next(item for item in at.expander if "Notifications" in item.label)
    labels = [button.label for button in notification.button]

    assert labels.index("WATCH ▸") < labels.index("OTHER ▸")
    text = " ".join(
        str(getattr(value, "value", value))
        for value in [*notification.markdown, *notification.caption]
    )
    assert "on watchlist" in text.lower()
