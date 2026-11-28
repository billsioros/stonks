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


def _stored_state(picks, *, pick_count=5) -> dict:
    return {
        "report": AdvisorReport("## Summary\nAll six headings follow.", tuple(picks)),
        "raw": "raw reply",
        "prompt": "prompt with candidate rows",
        "pick_count": pick_count,
        "fingerprint": universe_fingerprint({}, ""),
        "shortfall": 0,
    }


def _editor_table(at):
    editors = getattr(at, "data_editor", None) or at.dataframe
    return next(item for item in editors if "Weight %" in item.value.columns)


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


def test_generate_malformed_reply_shows_parse_error_and_raw(tmp_path, monkeypatch):
    from stonks import report_view

    db_path = tmp_path / "adv.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks([_stock("AAA"), _stock("BBB"), _stock("CCC")])
    monkeypatch.setattr(
        report_view, "request_advisor_report", lambda *a, **k: "NOT JSON"
    )
    at = _app_with_db(db_path, monkeypatch)
    at.session_state["advisor_pick_count"] = 3
    next(
        button for button in at.button if button.label == "✨ Generate recommendations"
    ).click().run()
    assert not at.exception, at.exception

    assert any("Could not parse advisor response" in str(e.value) for e in at.error)
    assert any(code.value == "NOT JSON" for code in at.code)
    state = at.session_state["advisor-llm-report"]
    assert state["report"] is None
    assert state["raw"] == "NOT JSON"
    assert "AAA" in state["prompt"]
    assert state["shortfall"] == 3


def test_zero_matching_rows_skips_provider(tmp_path, monkeypatch):
    from stonks import report_view

    def _forbidden(*args, **kwargs):
        raise AssertionError("provider called with zero matching rows")

    monkeypatch.setattr(report_view, "request_advisor_report", _forbidden)
    at = _app_with_db(tmp_path / "adv.db", monkeypatch)
    assert any(
        "No stocks match your current filters" in str(w.value) for w in at.warning
    )
    assert not any(
        button.label == "✨ Generate recommendations" for button in at.button
    )


def test_all_matching_symbols_already_held_skips_provider(tmp_path, monkeypatch):
    from stonks import report_view

    def _forbidden(*args, **kwargs):
        raise AssertionError("provider called with no new candidates")

    db_path = tmp_path / "adv.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks([_stock("AAA"), _stock("BBB")])
    store.add_position("AAA", 1, 100.0)
    store.add_position("BBB", 1, 100.0)
    monkeypatch.setattr(report_view, "request_advisor_report", _forbidden)
    at = _app_with_db(db_path, monkeypatch)
    assert any(
        "No new stocks match your current filters" in str(w.value) for w in at.warning
    )
    assert not any(
        button.label == "✨ Generate recommendations" for button in at.button
    )


def test_pick_count_change_marks_stale_disables_handoff_and_keeps_picks(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "adv.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks(
        [
            _stock("HLD", 100.0),
            _stock("AAA", 50.0),
            _stock("BBB", 50.0),
            _stock("CCC", 50.0),
        ]
    )
    store.add_position("HLD", 1, 100.0)
    at = _app_with_db(db_path, monkeypatch)
    at.session_state["advisor-llm-report"] = _stored_state(
        [
            AdvisorPick("AAA", 10.0, "a"),
            AdvisorPick("BBB", 10.0, "b"),
            AdvisorPick("CCC", 10.0, "c"),
        ]
    )
    at.run()
    assert not any("stale" in str(w.value).lower() for w in at.warning)
    fresh = next(
        button for button in at.button if button.label == "🧪 Send to backtest"
    )
    assert not fresh.proto.disabled

    at.session_state["advisor_pick_count"] = 1
    at.run()
    assert any("stale" in str(w.value).lower() for w in at.warning)
    stale = next(
        button for button in at.button if button.label == "🧪 Send to backtest"
    )
    assert stale.proto.disabled
    assert len(_editor_table(at).value) == 3


def test_sort_change_alone_does_not_mark_results_stale(tmp_path, monkeypatch):
    db_path = tmp_path / "adv.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks([_stock("HLD", 100.0), _stock("AAA", 50.0)])
    store.add_position("HLD", 1, 100.0)
    at = _app_with_db(db_path, monkeypatch)
    at.session_state["advisor-llm-report"] = _stored_state(
        [AdvisorPick("AAA", 20.0, "a")]
    )
    at.run()
    assert not any("stale" in str(w.value).lower() for w in at.warning)

    sort = next(box for box in at.selectbox if box.label == "📊 Sort by")
    sort.set_value("Stock Price").run()
    assert not at.exception, at.exception
    assert not any("stale" in str(w.value).lower() for w in at.warning)
    button = next(
        button for button in at.button if button.label == "🧪 Send to backtest"
    )
    assert not button.proto.disabled


def test_cap_warning_reaches_rail_and_drawer(tmp_path, monkeypatch):
    db_path = tmp_path / "adv.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks(
        [_stock("HLD", 100.0), _stock("AAA", 50.0), _stock("BBB", 50.0)]
    )
    store.add_position("HLD", 1, 100.0)
    at = _app_with_db(db_path, monkeypatch)
    at.session_state["advisor-llm-report"] = _stored_state(
        [AdvisorPick("AAA", 60.0, "a"), AdvisorPick("BBB", 60.0, "b")]
    )
    at.run()
    assert not at.exception, at.exception
    assert len([w for w in at.warning if "99%" in str(w.value)]) == 2
