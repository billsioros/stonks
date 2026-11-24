"""Regression tests for the viewport-height screener and compact UI pass."""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any

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
    at.session_state["active_filters"] = {}
    at.run()
    return at


def _simulated_backtest_result() -> dict[str, Any]:
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
    return result


def _app_css(at: AppTest) -> str:
    return "\n".join(
        str(item.value) for item in at.markdown if "<style>" in str(item.value)
    )


def _visible_markdown(at: AppTest) -> str:
    return " ".join(
        str(item.value) for item in at.markdown if "<style>" not in str(item.value)
    )


def test_screener_defaults_to_a_viewport_sized_page() -> None:
    assert config.DEFAULT_PAGE_SIZE == 25
    assert config.DEFAULT_PAGE_SIZE in config.PAGE_SIZE_OPTIONS
    assert config.SCREENER_TABLE_MAX_HEIGHT == 480


def test_screener_table_height_never_exceeds_the_viewport_cap() -> None:
    assert app._screener_table_height(5) == 264
    assert app._screener_table_height(10) == config.SCREENER_TABLE_MAX_HEIGHT
    assert app._screener_table_height(100) == config.SCREENER_TABLE_MAX_HEIGHT


def test_popular_and_saved_screen_cards_share_one_compact_grid() -> None:
    assert app._screen_column_ratios(False) == [3, 1, 1]
    assert app._screen_column_ratios(True) == [3, 1, 1]


def test_sidebar_screen_cards_get_narrow_width_styling() -> None:
    at = _app()
    css = _app_css(at)
    assert '[data-testid="stSidebar"] [class*="st-key-screen-"]' in css


def test_sidebar_screen_buttons_have_a_full_width_tap_target() -> None:
    at = _app()
    css = _app_css(at)
    rules = re.findall(
        r'\[data-testid="stSidebar"\] \[class\*="st-key-screen-"\] '
        r"\.stButton > button\s*\{[^}]*\}",
        css,
    )
    assert rules
    assert "min-width: 2.75rem" in rules[0]
    assert "width: 2.75rem" in rules[0]
    assert "flex: 0 0 2.75rem" in rules[0]
    assert "white-space: nowrap" in rules[0]


def test_footer_is_pinned_to_the_viewport_bottom() -> None:
    at = _app()
    css = _app_css(at)
    footer_rules = [
        rule
        for rule in re.findall(r"\.app-footer\s*\{[^}]*\}", css)
        if "position: fixed" in rule
    ]
    assert footer_rules
    assert "bottom: 0" in footer_rules[0]
    assert re.search(
        r"\.main \.block-container\s*\{[^}]*padding-bottom:\s*3\.5rem", css
    )


def test_backtest_results_label_the_yearly_table() -> None:
    at = _app()
    at.session_state[_RESULT_KEY] = _simulated_backtest_result()
    at.run()

    assert not at.exception
    assert any("Annual returns" in str(item.value) for item in at.caption)


def test_backtest_keeps_setup_sections_without_decorative_header() -> None:
    at = _app()
    at.session_state[_RESULT_KEY] = _simulated_backtest_result()
    at.run()

    assert not at.exception
    markdown = _visible_markdown(at)
    assert "bt-head" not in markdown
    assert "Portfolio lab" not in markdown
    assert "🧪 Portfolio Backtest" not in markdown
    assert "bt-section" in markdown
    assert "Setup" in markdown
    assert "Key metrics" in markdown


def test_watchlist_card_has_no_section_header_separator() -> None:
    at = _app()

    assert not at.exception
    markdown = _visible_markdown(at)
    assert '<div class="section-header">⭐ Watchlist</div>' not in markdown
    assert any(tab.label.startswith("⭐ Watchlist") for tab in at.tabs)


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
