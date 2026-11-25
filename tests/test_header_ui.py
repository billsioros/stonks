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


def test_footer_credits_data_sources() -> None:
    at = _app()
    html = " ".join(str(md.value) for md in at.markdown)
    assert "StockAnalysis.com" in html
    assert "HedgeFollow" in html


def test_html_page_title_is_just_the_brand(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(st, "set_page_config", lambda **kwargs: calls.append(kwargs))
    _app()
    assert calls[0]["page_title"] == "Stonks"


def test_page_icon_is_a_chart_emoji(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(st, "set_page_config", lambda **kwargs: calls.append(kwargs))
    _app()
    assert calls[0]["page_icon"] == "📈"


def test_masthead_uses_a_chart_emoji_instead_of_an_image() -> None:
    at = _app()
    mark = next(
        str(md.value) for md in at.markdown if 'class="sk-mark"' in str(md.value)
    )
    assert "📈" in mark
    assert "<img" not in mark
