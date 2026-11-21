"""AppTest coverage for moving between the screener and a symbol detail page."""

from streamlit.testing.v1 import AppTest


def _app() -> AppTest:
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()
    return at


def test_detail_page_without_data_shows_error_and_back() -> None:
    at = _app()
    at.session_state["page"] = "detail"
    at.session_state["detail_symbol"] = "ZZZZ"
    at.run()
    assert not at.exception
    assert any("No data for ZZZZ" in str(e.value) for e in at.error)


def test_back_control_restores_screener_and_filters() -> None:
    at = _app()
    before = dict(at.session_state["active_filters"])
    at.session_state["page"] = "detail"
    at.session_state["detail_symbol"] = "ZZZZ"
    at.run()
    back = next(b for b in at.button if "Back" in b.label)
    back.click().run()
    assert at.session_state["page"] == "screener"
    assert dict(at.session_state["active_filters"]) == before
