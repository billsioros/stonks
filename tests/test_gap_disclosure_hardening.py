"""Scope disclosure and deferred-minor regression coverage."""

from __future__ import annotations

from stonks import dossier as dossier_module
from stonks import report
from stonks.dossier import Check, build_dossier
from tests.test_deepdive_ui import _values
from tests.test_dossier import _annual_statement, _quality, _statements


def test_screener_prompt_states_scope_gaps_and_next_steps() -> None:
    prompt = (report.SYSTEM_INSTRUCTION + report.REPORT_SECTIONS).lower()

    assert "not a complete investment decision engine" in prompt
    assert "cannot prove a moat" in prompt
    assert "primary-filing review" in prompt
    assert "## evidence gaps and next steps" in prompt
    assert "suggested deep-dive next steps" in prompt
    assert "quality.*" in prompt
    assert "forward.*" in prompt


def test_symbol_prompt_states_scope_gaps_and_next_steps() -> None:
    prompt = (report.SYMBOL_SYSTEM_INSTRUCTION + report.SYMBOL_REPORT_SECTIONS).lower()

    assert "not a complete investment decision engine" in prompt
    assert "cannot prove a moat" in prompt
    assert "primary-filing review" in prompt
    assert "## evidence gaps and next steps" in prompt
    assert "suggested deep-dive next steps" in prompt
    assert "portfolio sizing" in prompt


def test_deep_dive_card_shows_scope_and_next_steps() -> None:
    values = _values()

    assert any("### Scope and next steps" in value for value in values)
    assert any(
        "not a complete investment decision engine" in value.lower() for value in values
    )
    assert any("Suggested deep-dive next steps" in value for value in values)


def test_fit_gate_compares_industries_case_insensitively() -> None:
    watchlist = (
        {"symbol": "AAPL", "industry": "technology"},
        {"symbol": "MSFT", "industry": "TECHNOLOGY"},
        {"symbol": "XOM", "industry": "energy"},
        {"symbol": "JPM", "industry": "financials"},
    )
    built = build_dossier("AAPL", row={"industry": "Technology"}, watchlist=watchlist)
    check = built.gates[-1].checks[1]

    assert check.status == "fail"
    assert "50%" in check.value


def test_fit_gate_distinguishes_the_two_missing_industry_cases() -> None:
    no_symbol_industry = (
        build_dossier(
            "AAPL",
            row={"industry": ""},
            watchlist=({"symbol": "AAPL", "industry": "Tech"},),
        )
        .gates[-1]
        .checks[1]
    )
    no_watchlist_industry = (
        build_dossier("AAPL", row={"industry": "Tech"}, watchlist=({"symbol": "AAPL"},))
        .gates[-1]
        .checks[1]
    )

    assert no_symbol_industry.value == "symbol industry unavailable"
    assert no_watchlist_industry.value == "watchlist industries unavailable"
    assert no_symbol_industry.status == "unverified"
    assert no_watchlist_industry.status == "unverified"


def test_fcf_stability_does_not_skip_a_missing_recent_year() -> None:
    statements = _statements(
        income_annual=_annual_statement({"fcf": [10.0, 9.0, 8.0, 7.0, None, 6.0]})
    )
    check = next(
        item
        for item in _quality({}, statements).checks
        if item.id == "quality.fcf_stability"
    )

    assert check.status == "unverified"
    assert "missing" in check.value


def test_forward_check_lookup_by_id_is_order_independent() -> None:
    checks = (
        Check("b", "B", "pass", "1", "> 0", "x"),
        Check("a", "A", "fail", "1", "> 0", "x"),
    )

    assert dossier_module._check_status(checks, "a") == "fail"
    assert dossier_module._check_status(checks, "z") == "unverified"
