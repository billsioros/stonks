"""AppTest coverage for the masthead's data-source line and page title."""

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest


def _app() -> AppTest:
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()
    return at


def test_masthead_has_no_auto_sync_indicator() -> None:
    at = _app()
    assert not [md for md in at.markdown if "Auto-sync" in str(md.value)]


def test_masthead_keeps_the_data_source_line() -> None:
    at = _app()
    assert any("data from StockAnalysis.com" in str(md.value) for md in at.markdown)


def test_html_page_title_is_just_the_brand(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(st, "set_page_config", lambda **kwargs: calls.append(kwargs))
    _app()
    assert calls[0]["page_title"] == "Stonks"
