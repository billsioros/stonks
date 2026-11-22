"""AppTest coverage for the backtest tab and the cross-check banner."""

import json

from streamlit.testing.v1 import AppTest

from stonks import sanity
from stonks.sanity import CheckResult
from stonks.store import SQLiteStore


def _app() -> AppTest:
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()
    return at


def test_backtest_tab_sits_next_to_the_watchlist() -> None:
    at = _app()
    assert not at.exception
    labels = [tab.label for tab in at.tabs]
    assert any("Screener" in label for label in labels)
    assert any("Watchlist" in label for label in labels)
    assert any("Backtest" in label for label in labels)


def _seed_report(results: list[CheckResult]) -> tuple[SQLiteStore, str | None]:
    store = SQLiteStore()
    previous = store.get_metadata(sanity.REPORT_KEY)
    sanity.save_report(store, results)
    return store, previous


def _restore(store: SQLiteStore, previous: str | None) -> None:
    if previous is None:
        with store._connect() as conn:
            conn.execute("DELETE FROM metadata WHERE key = ?", (sanity.REPORT_KEY,))
            conn.commit()
    else:
        store.save_metadata(sanity.REPORT_KEY, previous)


def test_banner_names_the_diverged_platform() -> None:
    store, previous = _seed_report(
        [
            CheckResult("StockAnalysis", "Default screener", True, "36 symbols"),
            CheckResult(
                "HedgeFollow",
                "Largest HF Buys",
                False,
                "the buys list could not be read",
            ),
        ]
    )
    try:
        at = _app()
        errors = [str(item.value) for item in at.error]
        assert any("Cross-check failed" in message for message in errors)
        assert any(
            "HedgeFollow" in str(md.value) and "could not be read" in str(md.value)
            for md in at.markdown
        )
        assert not any("Default screener" in str(md.value) for md in at.markdown), (
            "only diverged checks belong in the banner"
        )
    finally:
        _restore(store, previous)


def test_banner_is_hidden_when_every_check_agrees() -> None:
    store, previous = _seed_report(
        [CheckResult("StockAnalysis", "Default screener", True, "36 symbols")]
    )
    try:
        at = _app()
        assert not [
            item for item in at.error if "Cross-check failed" in str(item.value)
        ]
    finally:
        _restore(store, previous)


def test_banner_survives_a_report_with_no_results() -> None:
    store = SQLiteStore()
    previous = store.get_metadata(sanity.REPORT_KEY)
    store.save_metadata(sanity.REPORT_KEY, json.dumps({"checked_at": 0, "results": []}))
    try:
        at = _app()
        assert not at.exception
        assert not [
            item for item in at.error if "Cross-check failed" in str(item.value)
        ]
    finally:
        _restore(store, previous)
