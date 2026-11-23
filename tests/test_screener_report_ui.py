"""AppTest coverage for the screener AI report and the single screener heading."""

from streamlit.testing.v1 import AppTest


def _app() -> AppTest:
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()
    return at


def test_screener_heading_appears_only_as_the_tab_label() -> None:
    at = _app()
    assert "📊 Screener" in [tab.label for tab in at.tabs]
    assert not [md for md in at.markdown if "📊 Screener" in str(md.value)]


def test_ai_report_is_an_opt_in_expander() -> None:
    at = _app()
    assert [e for e in at.expander if "AI report" in str(e.label)]
    assert any(button.label == "Generate report" for button in at.button)
    assert not [md for md in at.markdown if "## Summary" in str(md.value)]
