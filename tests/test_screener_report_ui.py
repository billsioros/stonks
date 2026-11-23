"""AppTest coverage for the screener AI report and the single screener heading."""

from streamlit.testing.v1 import AppTest

from stonks.store import SQLiteStore

TEST_SYMBOL = "ZZSCR"


def _app() -> AppTest:
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()
    return at


def _seed_row(store: SQLiteStore) -> None:
    """The report lives below the table, so the screener needs at least one row."""
    store.save_stock(
        TEST_SYMBOL,
        {
            "description": "Screener report fixture",
            "market_cap": 1_000_000_000.0,
            "price": 10.0,
            "pe_ratio": 12.0,
        },
    )


def _drop_row(store: SQLiteStore) -> None:
    with store._connect() as conn:
        conn.execute("DELETE FROM stocks WHERE symbol = ?", (TEST_SYMBOL,))
        conn.commit()


def test_screener_heading_appears_only_as_the_tab_label() -> None:
    at = _app()
    assert "📊 Screener" in [tab.label for tab in at.tabs]
    assert not [md for md in at.markdown if "📊 Screener" in str(md.value)]


def test_ai_report_is_an_opt_in_expander() -> None:
    store = SQLiteStore()
    _seed_row(store)
    try:
        at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
        # The default screen filters hard enough to hide a single seeded row.
        at.session_state["active_filters"] = {}
        at.run()
        assert [e for e in at.expander if "AI report" in str(e.label)]
        assert any(button.label == "Generate report" for button in at.button)
        assert not [md for md in at.markdown if "## Summary" in str(md.value)]
    finally:
        _drop_row(store)
