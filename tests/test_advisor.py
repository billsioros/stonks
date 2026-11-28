import pytest

from stonks.report import (
    ADVISOR_HEADINGS,
    AdvisorPick,
    AdvisorReport,
    parse_advisor_reply,
)


def _reply(summary: str, picks: list[dict]) -> str:
    import json

    return json.dumps({"summary": summary, "picks": picks})


def _summary() -> str:
    return "\n\n".join(
        f"## {heading}\nText [Source: AAA, pe_ratio]" for heading in ADVISOR_HEADINGS
    )


def test_parse_advisor_reply_accepts_fenced_json():
    text = (
        "```json\n"
        + _reply(_summary(), [{"symbol": "aaa", "weight": 12.5, "reason": "Growth"}])
        + "\n```"
    )
    parsed = parse_advisor_reply(text, {"AAA"})
    assert parsed == AdvisorReport(
        summary=_summary(),
        picks=(AdvisorPick("AAA", 12.5, "Growth"),),
    )


def test_parse_advisor_reply_drops_unknown_and_duplicate_symbols():
    text = _reply(
        _summary(),
        [
            {"symbol": "AAA", "weight": 10, "reason": "first"},
            {"symbol": "AAA", "weight": 8, "reason": "duplicate"},
            {"symbol": "ZZZ", "weight": 5, "reason": "not in pool"},
        ],
    )
    parsed = parse_advisor_reply(text, {"AAA", "BBB"})
    assert parsed.picks == (AdvisorPick("AAA", 10.0, "first"),)


def test_parse_advisor_reply_rejects_missing_heading():
    text = _reply(
        "## Summary\nOnly one heading",
        [{"symbol": "AAA", "weight": 10, "reason": "ok"}],
    )
    with pytest.raises(ValueError, match="headings"):
        parse_advisor_reply(text, {"AAA"})


def test_parse_advisor_reply_rejects_bad_weight():
    text = _reply(_summary(), [{"symbol": "AAA", "weight": -1, "reason": "bad"}])
    with pytest.raises(ValueError, match="weight"):
        parse_advisor_reply(text, {"AAA"})


def test_parse_advisor_reply_rejects_empty_picks():
    text = _reply(_summary(), [{"symbol": "ZZZ", "weight": 10, "reason": "unknown"}])
    with pytest.raises(ValueError, match="no valid picks"):
        parse_advisor_reply(text, {"AAA"})


from stonks.report import advisor_report_prompt


def test_advisor_prompt_uses_only_supplied_universe_and_holdings():
    rows = [
        {"symbol": "AAA", "price": 10, "pe_ratio": 12, "industry": "Software"},
        {"symbol": "BBB", "price": 20, "pe_ratio": 18, "industry": "Hardware"},
    ]
    holdings = [
        {
            "symbol": "HLD",
            "weight_pct": 60.0,
            "industry": "Energy",
            "correlation": None,
        },
    ]
    prompt = advisor_report_prompt(rows, 5, holdings, 0.42)
    assert "AAA" in prompt and "BBB" in prompt and "HLD" in prompt
    assert "ZZZ" not in prompt
    assert "5" in prompt
    assert "0.42" in prompt
    assert "JSON" in prompt
    assert all(heading in prompt for heading in ADVISOR_HEADINGS)


from stonks.advisor import advisor_candidate_rows, build_what_if, universe_fingerprint


def test_build_what_if_under_100_percent():
    result = build_what_if(
        [("H1", 60.0), ("H2", 40.0)],
        [AdvisorPick("AAA", 10.0, "a"), AdvisorPick("BBB", 20.0, "b")],
        [True, True],
    )
    assert result.total_target_pct == pytest.approx(30.0)
    assert result.current_total == pytest.approx(100.0)
    assert result.added_cash == pytest.approx(42.8571428571)
    assert result.after_total == pytest.approx(142.8571428571)
    assert result.after_weights == pytest.approx((42.0, 28.0, 10.0, 20.0))
    assert result.cap_applied is False


def test_build_what_if_caps_over_100_percent():
    result = build_what_if(
        [("H1", 100.0)],
        [AdvisorPick("AAA", 60.0, "a"), AdvisorPick("BBB", 60.0, "b")],
        [True, True],
    )
    assert result.cap_applied is True
    assert result.after_weights == pytest.approx((1.0, 49.5, 49.5))
    assert result.total_target_pct == pytest.approx(99.0)


def test_build_what_if_unchecked_pick_keeps_its_weight():
    result = build_what_if(
        [("H1", 60.0), ("H2", 40.0)],
        [AdvisorPick("AAA", 10.0, "a"), AdvisorPick("BBB", 20.0, "b")],
        [True, False],
    )
    assert result.after_weights == pytest.approx((54.0, 36.0, 10.0))
    assert result.total_target_pct == pytest.approx(10.0)


def test_build_what_if_without_holdings_has_no_rail():
    result = build_what_if([], [AdvisorPick("AAA", 10.0, "a")], [True])
    assert result.current_total == 0.0
    assert result.added_cash == 0.0
    assert result.after_symbols == ()


def test_universe_fingerprint_tracks_filters_and_search():
    assert universe_fingerprint({"a": 1, "b": 2}, "") == universe_fingerprint(
        {"b": 2, "a": 1}, ""
    )
    assert universe_fingerprint({"a": 1}, "") != universe_fingerprint({"a": 1}, "nvda")


def test_candidate_rows_exclude_held_symbols():
    calls = []

    class FakeStore:
        def get_stocks(
            self, *, filters, search_query, sort_column, sort_ascending, page, page_size
        ):
            calls.append((filters, search_query, page, page_size))
            return ([{"symbol": "AAA"}, {"symbol": "HOLD"}, {"symbol": "BBB"}], 0, 3)

    rows = advisor_candidate_rows(
        FakeStore(),
        active_filters={"pe_ratio": {"max": 20}},
        search_query="soft",
        sort_column=None,
        sort_ascending=True,
        held_symbols={"HOLD"},
    )
    assert [row["symbol"] for row in rows] == ["AAA", "BBB"]
    assert calls[0][1] == "soft"
    assert calls[0][3] >= 3


from stonks.backtest_view import queue_backtest_settings


def test_queue_backtest_settings_merges_defaults_and_forces_percent_mode():
    state = {}
    queue_backtest_settings(
        {
            "symbols": ["H1", "AAA"],
            "weights": [70.0, 30.0],
            "initial": 142.857,
            "contribution": 0.0,
        },
        state,
    )
    pending = state["backtest_pending_load"]
    assert pending["symbols"] == ["H1", "AAA"]
    assert pending["weights"] == [70.0, 30.0]
    assert pending["initial"] == 142.857
    assert pending["contribution"] == 0.0
    assert pending["allocation_mode"] == "percent"
    assert pending["rebalance"] == "annual"


from stonks import backtest_view


def test_queue_backtest_settings_defaults_to_streamlit_session_state(monkeypatch):
    state = {}
    monkeypatch.setattr(backtest_view.st, "session_state", state)
    queue_backtest_settings({"symbols": ["AAA"], "allocation_mode": "amount"})
    pending = state["backtest_pending_load"]
    assert pending["symbols"] == ["AAA"]
    assert pending["allocation_mode"] == "percent"


from stonks import report_view
from stonks.report import ADVISOR_MAX_TOKENS, ADVISOR_SYSTEM_INSTRUCTION


def test_request_advisor_report_uses_advisor_instruction(monkeypatch):
    seen = {}

    def fake_cached(prompt, api_key, model, system_instruction, max_tokens):
        seen.update(
            prompt=prompt,
            api_key=api_key,
            model=model,
            system_instruction=system_instruction,
            max_tokens=max_tokens,
        )
        return "{}"

    monkeypatch.setattr(report_view, "_cached_report", fake_cached)
    assert report_view.request_advisor_report("prompt", "key", "model") == "{}"
    assert seen == {
        "prompt": "prompt",
        "api_key": "key",
        "model": "model",
        "system_instruction": ADVISOR_SYSTEM_INSTRUCTION,
        "max_tokens": ADVISOR_MAX_TOKENS,
    }


from streamlit.testing.v1 import AppTest

_DRAWER_APP = """
import streamlit as st
from stonks.report_view import render_advisor_report

render_advisor_report(
    scope_key="advisor-llm-report",
    heading="🤖 AI report",
    generate_clicked=False,
    generate_error=st.session_state["drawer_error"],
    cap_warning=st.session_state["drawer_cap"],
)
"""


def _drawer(state: dict, *, error: str | None = None, cap: bool = False) -> AppTest:
    at = AppTest.from_string(_DRAWER_APP, default_timeout=180)
    at.session_state["advisor-llm-report"] = state
    at.session_state["drawer_error"] = error
    at.session_state["drawer_cap"] = cap
    at.run()
    assert not at.exception, at.exception
    return at


def test_render_advisor_report_shows_summary_and_warnings():
    at = _drawer(
        {
            "report": AdvisorReport(summary="## Summary\nPick AAA", picks=()),
            "raw": "raw reply",
            "prompt": "PROMPT-AAA",
            "pick_count": 5,
            "fingerprint": "fp",
            "shortfall": 2,
        },
        error="provider failed",
        cap=True,
    )
    assert any("AI report" in str(e.label) for e in at.expander)
    assert any("## Summary" in str(md.value) for md in at.markdown)
    assert any("Model:" in str(c.value) for c in at.caption)
    assert any("provider failed" in str(err.value) for err in at.error)
    assert any("2 of the requested picks" in str(w.value) for w in at.warning)
    assert any("99%" in str(w.value) for w in at.warning)
    assert not at.button


def test_render_advisor_report_shows_raw_reply_when_parse_failed():
    at = _drawer(
        {
            "report": None,
            "raw": "NOT JSON",
            "prompt": "PROMPT-RAW",
            "pick_count": 5,
            "fingerprint": "fp",
            "shortfall": 0,
        }
    )
    assert any(code.value == "NOT JSON" for code in at.code)
    assert not any("99%" in str(w.value) for w in at.warning)
    assert not any("requested picks" in str(w.value) for w in at.warning)


def test_render_advisor_report_debug_toggle_shows_prompt():
    at = _drawer(
        {
            "report": None,
            "raw": "NOT JSON",
            "prompt": "PROMPT-DEBUG",
            "pick_count": 5,
            "fingerprint": "fp",
            "shortfall": 0,
        }
    )
    toggle = next(t for t in at.toggle if "Debug" in t.label)
    toggle.set_value(True).run()
    assert not at.exception, at.exception
    assert any(code.value == "PROMPT-DEBUG" for code in at.code)
