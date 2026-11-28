import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from stonks import app
from stonks.advisor import universe_fingerprint
from stonks.report import AdvisorPick, AdvisorReport
from stonks.store import SQLiteStore


def _stock(symbol: str, price: float = 100.0) -> dict:
    return {
        "symbol": symbol,
        "description": f"{symbol} Inc",
        "industry": "Software",
        "price": price,
        "currency": "USD",
    }


def _app_with_db(db_path, monkeypatch) -> AppTest:
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


def test_advisor_tab_comes_after_backtest(tmp_path, monkeypatch):
    at = _app_with_db(tmp_path / "adv.db", monkeypatch)
    assert [tab.label for tab in at.tabs] == [
        "📊 Screener",
        "⭐ Watchlist",
        "💼 Portfolio",
        "🧪 Backtest",
        "🤖 Advisor",
    ]


def test_empty_candidate_pool_skips_ai(tmp_path, monkeypatch):
    at = _app_with_db(tmp_path / "adv.db", monkeypatch)
    assert any(
        "No stocks match your current filters" in str(w.value) for w in at.warning
    )


def test_plain_rerun_does_not_call_provider(tmp_path, monkeypatch):
    from stonks import report_view

    store = SQLiteStore(db_path=tmp_path / "adv.db")
    store.replace_stocks([_stock("AAA")])

    def _forbidden(*args, **kwargs):
        raise AssertionError("provider called without Generate")

    monkeypatch.setattr(report_view, "request_advisor_report", _forbidden)
    at = _app_with_db(tmp_path / "adv.db", monkeypatch)
    assert not at.exception


def test_filter_change_marks_result_stale(tmp_path, monkeypatch):
    at = _app_with_db(tmp_path / "adv.db", monkeypatch)
    at.session_state["advisor-llm-report"] = {
        "report": None,
        "prompt": "old",
        "pick_count": 5,
        "fingerprint": "old-fingerprint",
    }
    at.run()
    assert any("stale" in str(w.value).lower() for w in at.warning)


def test_advisor_table_shows_pick_columns(tmp_path, monkeypatch):
    store = SQLiteStore(db_path=tmp_path / "adv.db")
    store.replace_stocks([_stock("AAA")])
    at = _app_with_db(tmp_path / "adv.db", monkeypatch)
    at.session_state["advisor-llm-report"] = {
        "report": AdvisorReport(
            "## Summary\nAll six headings follow.",
            (AdvisorPick("AAA", 20.0, "Growth"),),
        ),
        "prompt": "prompt",
        "pick_count": 5,
        "fingerprint": universe_fingerprint({}, ""),
    }
    at.run()
    # AppTest exposes st.data_editor as `dataframe` in Streamlit 1.56; newer
    # versions may expose a dedicated `data_editor` collection.
    editors = getattr(at, "data_editor", None) or at.dataframe
    table = next(item for item in editors if "Weight %" in item.value.columns)
    assert list(table.value.columns) == [
        "Select",
        "Rank",
        "Symbol",
        "Description",
        "Industry",
        "Weight %",
        "Why",
        "Portfolio correlation",
        "Price",
        "P/E",
        "PT upside %",
        "DCF upside %",
    ]


def test_handoff_uses_resulting_allocation_and_does_not_write_positions(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "adv.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks([_stock("HLD", 100.0), _stock("AAA", 50.0)])
    store.add_position("HLD", 1, 100.0)
    at = _app_with_db(db_path, monkeypatch)
    at.session_state["advisor-llm-report"] = {
        "report": AdvisorReport(
            "## Summary\nAll six headings follow.",
            (AdvisorPick("AAA", 20.0, "Growth"),),
        ),
        "prompt": "prompt",
        "pick_count": 5,
        "fingerprint": universe_fingerprint({}, ""),
    }
    at.run()
    before = store.get_positions()
    next(
        button for button in at.button if button.label == "🧪 Send to backtest"
    ).click().run()
    settings = at.session_state["backtest_settings"]
    assert settings["symbols"] == ["HLD", "AAA"]
    assert settings["weights"] == pytest.approx([80.0, 20.0])
    assert settings["initial"] == pytest.approx(125.0)
    assert settings["contribution"] == 0.0
    assert store.get_positions() == before


def test_no_priced_holdings_shows_warning_and_disabled_handoff(tmp_path, monkeypatch):
    store = SQLiteStore(db_path=tmp_path / "adv.db")
    store.replace_stocks([_stock("AAA")])
    at = _app_with_db(tmp_path / "adv.db", monkeypatch)
    at.session_state["advisor-llm-report"] = {
        # A stored report with no picks must still reach the no-priced rail.
        "report": AdvisorReport("## Summary\nAll six headings follow.", ()),
        "prompt": "prompt",
        "pick_count": 5,
        "fingerprint": universe_fingerprint({}, ""),
    }
    at.run()
    assert any(
        "Add a priced portfolio to use what-if" in str(w.value) for w in at.warning
    )
    button = next(
        button for button in at.button if button.label == "🧪 Send to backtest"
    )
    assert button.proto.disabled
