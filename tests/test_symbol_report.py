"""Tests for the single-symbol investment report prompt and request options."""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import Mock

from stonks import dossier, filing_evidence, report, report_view
from stonks.dossier import Check, Dossier, FilingEvidence, Gate

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


def _stub_pages(monkeypatch: Any) -> list[tuple[str, str, str, bool]]:
    """Replace the eleven provider reads with deterministic fixtures."""
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
    # Prompt building now gathers filing evidence too; keep every test offline.
    monkeypatch.setattr(
        "stonks.report_view.filing_evidence.build_filing_evidence",
        lambda _symbol, **_kwargs: FilingEvidence.empty(),
    )
    return calls


def test_symbol_prompt_gathering_forces_every_page_refresh(monkeypatch: Any) -> None:
    calls = _stub_pages(monkeypatch)

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


def test_prompt_parts_build_one_dossier_with_unverified_filings(
    monkeypatch: Any,
) -> None:
    _stub_pages(monkeypatch)
    calls: list[int] = []
    original = dossier.build_dossier

    def counted(*args: Any, **kwargs: Any) -> Dossier:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(report_view.dossier, "build_dossier", counted)

    prompt, built = report_view.symbol_report_prompt_parts(_Store(), "NVDA")

    assert len(calls) == 1
    assert "## Verdict" in prompt
    filings = next(gate for gate in built.gates if gate.key == "filings")
    assert dossier.gate_status(filings.checks) == "unverified"


def test_report_path_supplies_the_full_universe_as_peers(monkeypatch: Any) -> None:
    _stub_pages(monkeypatch)
    rows = [
        {
            **ROW,
            "industry": "Semiconductors",
            "operating_margin_pct": 30.0 + index,
            "revenue_growth_5y_pct": 20.0 + index,
        }
        for index in range(6)
    ]

    class UniverseStore:
        def get_stocks(self, **kwargs: Any) -> tuple[list[dict[str, Any]], int, int]:
            if kwargs.get("filters", {}).get("symbol"):
                return [rows[0]], 1, 1
            # Match the real store's page_size clamp so page_size=0 is caught.
            page_size = max(1, min(int(kwargs.get("page_size", 1)), 100_000))
            return rows[:page_size], 1, len(rows)

    captured: dict[str, Any] = {}
    original = dossier.build_dossier

    def capture(*args: Any, **kwargs: Any) -> Dossier:
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(report_view.dossier, "build_dossier", capture)

    _, built = report_view.symbol_report_prompt_parts(UniverseStore(), "NVDA")

    assert len(captured["peers"]) >= 5
    checks = {check.id: check for gate in built.gates for check in gate.checks}
    assert "fewer than five peers" not in checks["quality.margin_vs_industry"].value
    assert checks["quality.growth_vs_industry"].status != "unverified"


def test_prompt_for_hands_the_same_dossier_to_its_callback(monkeypatch: Any) -> None:
    _stub_pages(monkeypatch)
    seen: list[Dossier] = []

    prompt = report_view.symbol_report_prompt_for(
        _Store(), "NVDA", on_dossier=seen.append
    )

    assert len(seen) == 1
    assert "## Verdict" in prompt
    assert seen[0].symbol == "NVDA"


def test_edgar_failure_still_produces_a_memo(monkeypatch: Any) -> None:
    _stub_pages(monkeypatch)
    builder = Mock(
        return_value=FilingEvidence(reason="EDGAR_USER_AGENT not configured")
    )
    monkeypatch.setattr(
        "stonks.report_view.filing_evidence.build_filing_evidence", builder
    )

    prompt, built = report_view.symbol_report_prompt_parts(_Store(), "NVDA")

    builder.assert_called_once()
    assert builder.call_args.args == ("NVDA",)
    assert set(builder.call_args.kwargs) == {"store"}
    assert "## Verdict" in prompt
    assert "EDGAR_USER_AGENT not configured" in prompt
    filings = next(gate for gate in built.gates if gate.key == "filings")
    assert dossier.gate_status(filings.checks) == "unverified"
    assert filings.summary == "EDGAR_USER_AGENT not configured"
    # The memo prompt still reaches the model and yields an answer.
    assert report.request_report(prompt, api_key="k", client=_Client()) == (
        "## TL;DR\nYES."
    )


def test_cache_failure_still_produces_a_memo(monkeypatch: Any) -> None:
    real_builder = filing_evidence.build_filing_evidence
    _stub_pages(monkeypatch)
    monkeypatch.setenv("EDGAR_USER_AGENT", "stonks/1.0 (test@example.com)")
    # Undo the offline builder stub: exercise the real builder against a broken
    # cache so the "never raises" promise is tested end to end.
    monkeypatch.setattr(
        "stonks.report_view.filing_evidence.build_filing_evidence", real_builder
    )

    class CacheFailureStore(_Store):
        def cache_get(self, *args: Any, **kwargs: Any) -> Any:
            raise sqlite3.OperationalError("database is locked")

    prompt, built = report_view.symbol_report_prompt_parts(CacheFailureStore(), "NVDA")

    assert "EDGAR cache unavailable" in prompt
    filings = next(gate for gate in built.gates if gate.key == "filings")
    assert dossier.gate_status(filings.checks) == "unverified"
    assert filings.summary == "EDGAR cache unavailable"
    assert report.request_report(prompt, api_key="k", client=_Client()) == (
        "## TL;DR\nYES."
    )


def test_guidance_hits_reach_the_forward_gate(monkeypatch: Any) -> None:
    _stub_pages(monkeypatch)
    hit = {
        "phrase": "guidance",
        "count": 1,
        "filing_date": "2026-11-01",
        "accession": "000-2026-01",
        "form": "8-K",
        "url": "https://www.sec.gov/Archives/8k",
    }
    builder = Mock(return_value=FilingEvidence(guidance_hits=(hit,)))
    monkeypatch.setattr(
        "stonks.report_view.filing_evidence.build_filing_evidence", builder
    )

    _, built = report_view.symbol_report_prompt_parts(_Store(), "NVDA")

    forward = next(gate for gate in built.gates if gate.key == "forward")
    check = next(c for c in forward.checks if c.id == "forward.guidance_present")
    assert check.status == "pass"
    assert "1 filing(s) mention guidance" in check.value


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


def _dossier(value: str = "1.0 vs 1.2") -> Dossier:
    return Dossier(
        symbol="NVDA",
        as_of="2026-11-23T09:00:00Z",
        gates=(
            Gate(
                "quality",
                "Business quality",
                (
                    Check(
                        "quality.roic_5y",
                        "ROIC",
                        "pass",
                        "14.2%",
                        ">= 10%",
                        "PASS-EVIDENCE-MARKER",
                    ),
                    Check(
                        "quality.cash_conversion",
                        "Cash conversion",
                        "unverified",
                        "net income missing",
                        ">= 0.8",
                        "screener.net_income",
                    ),
                ),
                "One check needs input",
            ),
            Gate(
                "filings",
                "Primary filings",
                (
                    Check(
                        "filings.revenue_crosscheck",
                        "Revenue",
                        "fail",
                        value,
                        "<= 1%",
                        "acc 0000320193-25-000001",
                    ),
                ),
                "Revenue differs",
            ),
        ),
        conflicts=(f"revenue differs: {value} (0000320193-25-000001)",),
        red_flags=("material weakness (2025-10-30)",),
        provenance=(("screener", "row snapshot", "1h"),),
        coverage=0.5,
    )


def test_symbol_prompt_leads_with_the_verdict_before_the_data() -> None:
    prompt = report.symbol_report_prompt("NVDA", row=ROW, dossier=_dossier())
    assert prompt.index("## Verdict") < prompt.index("Symbol: NVDA")
    for check_id in (
        "quality.roic_5y",
        "quality.cash_conversion",
        "filings.revenue_crosscheck",
    ):
        assert check_id in prompt
    assert "Business quality" in prompt
    assert "fail" in prompt and "unverified" in prompt


def test_unverified_checks_are_listed_under_the_required_heading() -> None:
    prompt = report.symbol_report_prompt("NVDA", dossier=_dossier())
    heading = "## What this dossier could not verify"
    assert heading in prompt
    section = prompt.split(heading, 1)[1].split("## ", 1)[0]
    assert "quality.cash_conversion" in section
    assert "net income missing" in section
    assert "screener.net_income" not in section
    assert "quality.roic_5y" not in section


def test_unverified_section_asks_for_coverage_in_the_tldr() -> None:
    prompt = report.symbol_report_prompt("NVDA", dossier=_dossier())
    heading = "## What this dossier could not verify"
    section = prompt.split(heading, 1)[1]
    assert "coverage" in section.lower()
    assert "TL;DR" in section

    instruction = report.SYMBOL_SYSTEM_INSTRUCTION
    assert "coverage" in instruction.lower()
    assert "TL;DR" in instruction


def test_symbol_system_instruction_forbids_unsupported_claims() -> None:
    instruction = report.SYMBOL_SYSTEM_INSTRUCTION
    assert "moat" in instruction and "catalyst" in instruction
    assert "unverified" in instruction
    assert "check id" in instruction


def test_dossier_block_omits_passing_evidence_and_changes_with_the_dossier() -> None:
    first = report.dossier_block(_dossier())
    second = report.dossier_block(_dossier("1.0 vs 1.9"))
    assert "PASS-EVIDENCE-MARKER" not in first
    assert "1.0 vs 1.2" in first
    assert first != second


def test_symbol_prompt_without_a_dossier_is_unchanged() -> None:
    prompt = report.symbol_report_prompt("NVDA", row=ROW)
    assert "## Verdict" not in prompt
    assert "## What this dossier could not verify" not in prompt
    assert "Symbol: NVDA" in prompt


def test_symbol_report_uses_the_larger_thinking_budget() -> None:
    assert report.SYMBOL_MAX_TOKENS == 4000
    assert report_view.SYMBOL_MAX_TOKENS == 4000


def test_build_dossier_carries_filing_conflicts_hits_and_provenance() -> None:
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "end": "2025-09-27",
                                "filed": "2025-10-30",
                                "form": "10-K",
                                "accn": "000-2025-01",
                                "val": 1_000_000_000,
                            }
                        ]
                    }
                }
            }
        }
    }
    hit = {
        "phrase": "material weakness",
        "count": 1,
        "filing_date": "2025-10-30",
        "accession": "000-2025-02",
        "url": "https://www.sec.gov/Archives/x",
    }
    evidence = FilingEvidence(
        cik="0000320193",
        facts=facts,
        hits=(hit,),
        latest_10k="2025-10-30",
    )

    built = dossier.build_dossier(
        "NVDA",
        row={"revenue": 1_100_000_000.0},
        filing_evidence=evidence,
        today="2026-11-23",
    )

    assert any("filings.revenue" in item for item in built.conflicts)
    assert any(
        "material weakness" in item and "https://www.sec.gov/Archives/x" in item
        for item in built.red_flags
    )
    assert any(
        source == "sec" and "0000320193" in detail
        for source, detail, _ in built.provenance
    )
