import streamlit as st
from streamlit.testing.v1 import AppTest

from stonks import app
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
