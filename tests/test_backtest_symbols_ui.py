"""AppTest coverage for roomies-style symbol management in the backtest tab."""

from __future__ import annotations

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from stonks.backtest_view import _SETTINGS_KEY, default_settings


@pytest.fixture(autouse=True)
def _clear_resource_cache_after_each_test() -> None:
    yield
    st.cache_resource.clear()


def _settings(symbols: list[str], weights: list[float] | None = None) -> dict:
    settings = default_settings()
    settings["symbols"] = symbols
    settings["weights"] = weights
    return settings


def _app(settings: dict | None = None) -> AppTest:
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    if settings is not None:
        at.session_state[_SETTINGS_KEY] = settings
    at.run()
    return at


def _add_expander(at: AppTest):
    return next(item for item in at.expander if "Add symbol" in item.label)


def test_backtest_lists_symbols_with_edit_and_delete_actions() -> None:
    at = _app(_settings(["AAA", "BBB"], [60.0, 40.0]))

    assert not at.exception
    assert _add_expander(at).label == "Add symbol"
    markdown = " ".join(str(getattr(md, "value", md)) for md in at.markdown)
    assert "AAA" in markdown
    assert "BBB" in markdown
    assert any(button.key == "bt_edit_symbol_0" for button in at.button)
    assert any(button.key == "bt_delete_symbol_1" for button in at.button)


def test_backtest_adds_a_symbol_from_the_expander() -> None:
    at = _app(_settings(["AAA"]))

    panel = _add_expander(at)
    panel.text_input[0].set_value("BBB")
    next(button for button in panel.button if button.label == "Add").click().run()

    assert not at.exception
    assert at.session_state[_SETTINGS_KEY]["symbols"] == ["AAA", "BBB"]


def test_backtest_edits_then_deletes_a_symbol() -> None:
    at = _app(_settings(["AAA", "BBB"], [60.0, 40.0]))

    next(
        button for button in at.button if button.key == "bt_edit_symbol_0"
    ).click().run()
    panel = next(item for item in at.expander if "Edit symbol" in item.label)
    assert panel.text_input[0].value == "AAA"
    panel.text_input[0].set_value("CCC")
    next(
        button for button in panel.button if button.label == "Save changes"
    ).click().run()

    assert not at.exception
    assert at.session_state[_SETTINGS_KEY]["symbols"] == ["CCC", "BBB"]

    next(
        button for button in at.button if button.key == "bt_delete_symbol_1"
    ).click().run()

    assert not at.exception
    assert at.session_state[_SETTINGS_KEY]["symbols"] == ["CCC"]
