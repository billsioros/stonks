"""Tests for the screener AI report: prompt payload, request and errors."""

import httpx
import pytest
from openrouter import errors as or_errors

from stonks import report
from stonks.config import COLUMN_DISPLAY_NAMES

ROWS = [
    {
        "symbol": "AAA",
        "description": "Acme Widgets Inc",
        "industry": "Software",
        "price": 100.0,
        "pe_ratio": 12.0,
        "pt_upside_pct": 10.0,
        "dcf_upside_pct": 5.0,
        "dividend_yield_pct": 1.0,
        "revenue_growth_5y_pct": 8.0,
        "hedge_fund_buys": 1,
    },
    {
        "symbol": "BBB",
        "description": "Beta Holdings Ltd",
        "industry": "Software",
        "price": 50.0,
        "pe_ratio": 18.0,
        "pt_upside_pct": 20.0,
        "dcf_upside_pct": 12.0,
        "dividend_yield_pct": 3.0,
        "revenue_growth_5y_pct": 4.0,
        "hedge_fund_buys": 0,
    },
    {
        "symbol": "CCC",
        "description": "Gamma Corp",
        "industry": "Energy",
        "price": 25.0,
        "pe_ratio": 30.0,
        "pt_upside_pct": 30.0,
        "dcf_upside_pct": None,
        "dividend_yield_pct": 5.0,
        "revenue_growth_5y_pct": 1.0,
        "hedge_fund_buys": 0,
    },
]


def test_prompt_uses_the_shared_report_skeleton() -> None:
    prompt = report.screener_report_prompt(ROWS, 3)
    for heading in (
        "## Summary",
        "## Key numbers",
        "## Observations",
        "## What to look at",
        "## TL;DR",
    ):
        assert heading in prompt
    assert "Data:\n" in prompt


def test_prompt_reports_all_matching_stocks_and_active_filters() -> None:
    prompt = report.screener_report_prompt(
        ROWS,
        3,
        filters={"pe_ratio": {"max": 20.0}},
        search_query="AAA",
        view_preset="Valuation",
    )
    assert "| Matching stocks | 3 |" in prompt
    assert "pe_ratio" in prompt
    assert "AAA" in prompt
    assert "Valuation" in prompt


def test_prompt_summarizes_every_row_not_just_the_visible_page() -> None:
    prompt = report.screener_report_prompt(ROWS, 3)
    assert "| AAA | +10.0% |" in prompt
    assert "| BBB | +20.0% |" in prompt
    assert "| CCC | +30.0% |" in prompt


def test_prompt_leaves_company_descriptions_out() -> None:
    prompt = report.screener_report_prompt(ROWS, 3)
    assert "Acme Widgets Inc" not in prompt
    assert "Beta Holdings Ltd" not in prompt
    assert "AAA" in prompt


def test_prompt_skips_missing_and_non_numeric_values() -> None:
    rows = [
        {"symbol": "AAA", "pt_upside_pct": None},
        {"symbol": "BBB", "pt_upside_pct": "n/a"},
        {"symbol": "CCC", "pt_upside_pct": 15.0},
    ]
    prompt = report.screener_report_prompt(rows, 3)
    assert "| Median PT upside | +15.0% |" in prompt
    assert "| CCC | +15.0% |" in prompt
    assert "AAA" not in prompt
    assert "BBB" not in prompt


def test_prompt_reports_n_a_when_a_metric_has_no_values() -> None:
    rows = [
        {"symbol": "AAA", "pt_upside_pct": None},
        {"symbol": "BBB", "pt_upside_pct": "n/a"},
    ]
    prompt = report.screener_report_prompt(rows, 2)
    assert "| Median PT upside | n/a |" in prompt


def test_prompt_with_no_rows_reads_zero_and_empty_tables() -> None:
    prompt = report.screener_report_prompt([], 0)
    assert "| Matching stocks | 0 |" in prompt
    assert "- (none)" in prompt


def test_prompt_carries_every_screener_column() -> None:
    prompt = report.screener_report_prompt(ROWS, len(ROWS))
    for label in COLUMN_DISPLAY_NAMES.values():
        if label in {"Symbol", "Company"}:
            continue
        assert label in prompt, label


def test_prompt_reports_lynch_fair_value_and_upside() -> None:
    rows = [
        {"symbol": "AAA", "lynch_fair_value": 100.0, "lynch_upside_pct": 20.0},
        {"symbol": "BBB", "lynch_fair_value": 200.0, "lynch_upside_pct": 40.0},
    ]
    prompt = report.screener_report_prompt(rows, len(rows))
    assert "| Lynch Fair Value | 150.00 | 100.00 | 200.00 | 2 |" in prompt
    assert "| Lynch Upside % | 30.00 | 20.00 | 40.00 | 2 |" in prompt


def test_prompt_breaks_down_every_categorical_column() -> None:
    rows = [
        {
            "symbol": "AAA",
            "exchange": "NASDAQ",
            "rating": "Buy",
            "industry": "Software",
        },
        {"symbol": "BBB", "exchange": "NYSE", "rating": "Hold", "industry": "Energy"},
    ]
    prompt = report.screener_report_prompt(rows, len(rows))
    for value in ("NASDAQ", "NYSE", "Buy", "Hold", "Software", "Energy"):
        assert f"| {value} | 1 |" in prompt


class _Choice:
    def __init__(self, content: str | None) -> None:
        self.message = type("Message", (), {"content": content})()


class _Result:
    def __init__(self, choices: list[_Choice]) -> None:
        self.choices = choices


class _Chat:
    def __init__(self, result: _Result) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def send(self, **kwargs: object) -> _Result:
        self.calls.append(kwargs)
        return self.result


class _Client:
    def __init__(self, result: _Result) -> None:
        self.chat = _Chat(result)


def test_request_report_sends_only_the_prompt_and_system_instruction() -> None:
    client = _Client(_Result([_Choice("## Summary\nBullish.")]))
    reply = report.request_report("Data:\nsome figures", api_key="k", client=client)
    assert reply == "## Summary\nBullish."
    call = client.chat.calls[0]
    assert call["messages"] == [
        {"role": "system", "content": report.SYSTEM_INSTRUCTION},
        {"role": "user", "content": "Data:\nsome figures"},
    ]
    assert call["model"] == "openrouter/free"
    assert call["temperature"] == 0.4
    assert call["max_tokens"] == 1024
    assert call["stream"] is False


@pytest.mark.parametrize("choices", [[], [_Choice(None)]])
def test_request_report_returns_empty_when_the_model_has_no_text(
    choices: list[_Choice],
) -> None:
    client = _Client(_Result(choices))
    assert report.request_report("Data:", api_key="k", client=client) == ""


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, "rate limit"),
        (401, "OPENROUTER_API_KEY"),
        (503, "busy right now"),
    ],
)
def test_explain_error_names_the_actionable_failure(status: int, expected: str) -> None:
    response = httpx.Response(
        status, request=httpx.Request("POST", "https://openrouter.ai/api/v1")
    )
    exc = or_errors.OpenRouterError("failed", response)
    assert expected.lower() in report.explain_error(exc).lower()


def test_explain_error_handles_a_network_failure() -> None:
    assert "network" in report.explain_error(httpx.ConnectError("offline")).lower()
