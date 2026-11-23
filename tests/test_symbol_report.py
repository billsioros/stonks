"""Tests for the single-symbol investment report prompt and request options."""

from __future__ import annotations

from typing import Any

from stonks import report, report_view

ROW: dict[str, Any] = {
    "symbol": "NVDA",
    "description": "Nvidia",
    "price": 100.0,
    "pe_ratio": 40.0,
    "dcf_upside_pct": 25.0,
    "lynch_fair_value": 120.0,
    "lynch_upside_pct": 20.0,
    "pt_upside_pct": 15.0,
    "dividend_yield_pct": 0.2,
    "debt_to_equity": 0.3,
    "short_pct": 1.2,
}

OVERVIEW: dict[str, Any] = {
    "summary": "Designs chips.",
    "revenue": "12B",
    "pe_ratio": "40",
    "news": [
        {
            "title": "Strong quarter",
            "source": "Reuters",
            "ago": "2d",
            "summary": " Beat.",
        }
    ],
}

STATISTICS: list[dict[str, Any]] = [
    {
        "key": "financialPosition",
        "title": "Financial Position",
        "text": "Debt and coverage",
        "items": [
            {
                "id": "interestCoverage",
                "title": "Interest coverage",
                "value": "8.5",
                "hover": "8.52",
            },
            {"id": "zScore", "title": "Z score", "value": "3.1", "hover": "3.12"},
        ],
    }
]

FORECAST: dict[str, Any] = {
    "targets": {
        "low": 80,
        "median": 120,
        "average": 118,
        "high": 150,
        "count": 12,
        "updated": "2026-11-01",
    },
    "current_ratings": {
        "consensus": "Buy",
        "score": 4.2,
        "count": 20,
        "strongBuy": 10,
        "buy": 6,
        "hold": 3,
        "sell": 1,
        "strongSell": 0,
    },
    "estimates": {"annual": {"epsNext": {"last": 4.0, "this": 5.0, "growth": 25.0}}},
    "ratings": [
        {
            "firm": "Example",
            "analyst": "A",
            "action": "raises",
            "target_now": 130,
            "target_old": 120,
            "rating_new": "Buy",
            "rating_old": "Hold",
            "date": "2026-11-01",
            "time": "",
        }
    ],
}

STATEMENTS: dict[str, dict[str, Any]] = {
    "income-statement annual": {
        "statement": "income-statement",
        "period": "annual",
        "periods": [
            {"key": "FY2025", "label": "FY2025", "is_ttm": False},
            {"key": "TTM", "label": "TTM", "is_ttm": True},
        ],
        "rows": [{"id": "revenue", "label": "Revenue", "values": [100, 120]}],
    }
}

HISTORY = [
    {"date": "2025-11-21", "close": 80.0},
    {"date": "2026-11-20", "close": 100.0},
]


def _prompt() -> str:
    return report.symbol_report_prompt(
        "NVDA",
        row=ROW,
        overview=OVERVIEW,
        statistics=STATISTICS,
        forecast=FORECAST,
        statements=STATEMENTS,
        history=HISTORY,
    )


def test_symbol_prompt_has_the_full_decision_skeleton() -> None:
    prompt = _prompt()
    for heading in (
        "## Business and moat",
        "## Growth and profitability",
        "## Cash flow and balance sheet",
        "## Valuation at today's price",
        "## Risks",
        "## What would change the answer",
        "## TL;DR",
    ):
        assert heading in prompt
    assert "YES" in prompt
    assert "NO" in prompt
    assert "Data:\n" in prompt
    assert prompt.index("## Business and moat") < prompt.index("Data:\n")


def test_symbol_prompt_carries_today_price_and_valuation() -> None:
    prompt = _prompt()
    assert "Price today" in prompt
    assert "100.00" in prompt
    assert "DCF Upside %" in prompt
    assert "+25.0%" in prompt
    assert "Lynch Fair Value" in prompt
    assert "120.00" in prompt
    assert "Analyst price target (median)" in prompt
    assert "120" in prompt


def test_symbol_prompt_includes_financial_statement_values() -> None:
    prompt = _prompt()
    assert "Income statement — annual" in prompt
    assert "FY2025" in prompt
    assert "TTM" in prompt
    assert "Revenue" in prompt
    assert "120.00" in prompt


def test_statement_tables_keep_only_recent_periods() -> None:
    data = {
        "periods": [
            {"key": f"FY{year}", "label": f"FY{year}", "is_ttm": False}
            for year in (2025, 2024, 2023, 2022, 2021)
        ],
        "rows": [
            {
                "id": "revenue",
                "label": "Revenue",
                "values": [100, 90, 80, 70, 60],
            }
        ],
    }
    prompt = report.symbol_report_prompt(
        "NVDA", statements={"income-statement annual": data}
    )
    assert "FY2025" in prompt
    assert "FY2023" in prompt
    assert "FY2021" not in prompt
    assert "Showing the 3 most recent periods" in prompt


def test_symbol_prompt_includes_statistics_and_news() -> None:
    prompt = _prompt()
    assert "Interest coverage" in prompt
    assert "8.52" in prompt
    assert "Z score" in prompt
    assert "Strong quarter" in prompt


def test_symbol_prompt_marks_absent_sections_unavailable() -> None:
    prompt = report.symbol_report_prompt(
        "ZZZZ", statements={"income-statement annual": {}}
    )
    assert "not available" in prompt
    assert "Financial statements:\nnot available" in prompt
    assert "ZZZZ" in prompt


class _Store:
    def get_stocks(self, **kwargs: Any) -> tuple[list[dict[str, Any]], int, int]:
        return [ROW], 1, 1


def test_symbol_prompt_gathering_forces_every_page_refresh(monkeypatch: Any) -> None:
    calls: list[tuple[str, str, str, bool]] = []

    def fake_load_page(
        store: Any,
        symbol: str,
        page: str,
        *,
        statement: str = "income-statement",
        period: str = "annual",
        force: bool = False,
        fetch: Any = None,
    ) -> tuple[Any, Any]:
        calls.append((page, statement, period, force))
        return {"raw": page}, 1.0

    monkeypatch.setattr(report_view.detail, "load_page", fake_load_page)
    monkeypatch.setattr(report_view.detail, "load_history", lambda *a, **k: HISTORY)
    monkeypatch.setattr(
        report_view.detail_parse, "parse_overview", lambda data: OVERVIEW
    )
    monkeypatch.setattr(
        report_view.detail_parse, "parse_statistics", lambda data: STATISTICS
    )
    monkeypatch.setattr(
        report_view.detail_parse, "parse_forecast", lambda data: FORECAST
    )
    monkeypatch.setattr(
        report_view.detail_parse,
        "parse_statement",
        lambda data: STATEMENTS["income-statement annual"],
    )

    prompt = report_view.symbol_report_prompt_for(_Store(), "NVDA")

    assert len(calls) == 11
    assert all(force for _, _, _, force in calls)
    assert {page for page, _, _, _ in calls} == {
        "overview",
        "statistics",
        "forecast",
        "financials",
    }
    assert "Revenue" in prompt
    assert "Strong quarter" in prompt


class _Choice:
    def __init__(self, content: str | None) -> None:
        self.message = type("Message", (), {"content": content})()


class _Result:
    def __init__(self, choices: list[_Choice]) -> None:
        self.choices = choices


class _Chat:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send(self, **kwargs: Any) -> _Result:
        self.calls.append(kwargs)
        return _Result([_Choice("## TL;DR\nYES.")])


class _Client:
    def __init__(self) -> None:
        self.chat = _Chat()


def test_request_report_accepts_a_longer_thorough_response() -> None:
    client = _Client()
    reply = report.request_report(
        "Data:",
        api_key="k",
        client=client,
        system_instruction="You are a financial analyst.",
        max_tokens=2500,
    )
    assert reply == "## TL;DR\nYES."
    call = client.chat.calls[0]
    assert call["messages"][0] == {
        "role": "system",
        "content": "You are a financial analyst.",
    }
    assert call["max_tokens"] == 2500
