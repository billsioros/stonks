"""The dossier is the deterministic half of the deep dive.

These tests pin the status algebra: a gate fails on any failure, is unverified
when nothing fails but something could not be checked, and passes only when
every applicable check passed. Coverage is passed/applicable, so checks that do
not apply never dilute the number.
"""

from __future__ import annotations

from stonks.dossier import (
    Check,
    Dossier,
    Gate,
    coverage,
    forward_gate,
    gate_status,
    industry_medians,
    quality_gate,
)


def _check(status: str, check_id: str = "q.a") -> Check:
    return Check(check_id, "A", status, "1", ">= 0", "test")  # type: ignore[arg-type]


def _gate(*checks: Check) -> Gate:
    return Gate("quality", "Quality", checks, "")


def test_gate_status_fails_on_any_failure() -> None:
    assert gate_status((_check("pass"), _check("fail"))) == "fail"


def test_gate_status_is_unverified_when_nothing_fails_but_something_is_unknown() -> (
    None
):
    assert gate_status((_check("pass"), _check("unverified"))) == "unverified"


def test_gate_status_passes_only_when_every_applicable_check_passes() -> None:
    assert gate_status((_check("pass"), _check("not_applicable"))) == "pass"


def test_gate_status_is_not_applicable_when_no_check_applies() -> None:
    assert (
        gate_status((_check("not_applicable"), _check("not_applicable")))
        == "not_applicable"
    )


def test_gate_status_of_an_empty_gate_is_unverified_not_pass() -> None:
    assert gate_status(()) == "unverified"


def test_coverage_excludes_not_applicable_checks() -> None:
    gate = _gate(_check("pass"), _check("unverified"), _check("not_applicable"))
    assert coverage((gate,)) == 0.5


def test_coverage_is_zero_when_nothing_applies() -> None:
    assert coverage((_gate(_check("not_applicable")),)) == 0.0


def test_coverage_spans_every_gate() -> None:
    first = _gate(_check("pass"))
    second = Gate("forward", "Forward", (_check("fail"),), "")
    assert coverage((first, second)) == 0.5


def test_checks_are_immutable_so_one_gate_cannot_edit_another() -> None:
    check = _check("pass")
    try:
        check.status = "fail"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("Check should be frozen")


def test_dossier_carries_its_evidence_beyond_the_gates() -> None:
    dossier = Dossier(
        symbol="AAPL",
        as_of="2026-11-23T09:00:00Z",
        gates=(_gate(_check("pass")),),
        conflicts=("revenue differs: 1.0 vs 1.2 (0000320193-25-000001)",),
        red_flags=("material weakness (2025-10-30)",),
        provenance=(("screener", "row snapshot", "1h"),),
        coverage=1.0,
    )
    assert dossier.symbol == "AAPL"
    assert dossier.conflicts and dossier.red_flags
    assert dossier.provenance[0][0] == "screener"


# ── Task 2: quality gate ─────────────────────────────────────────────


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "TEST",
        "industry": "Semiconductors",
        "roic_5y_avg_pct": 14.0,
        "roic_pct": 15.0,
        "operating_margin_pct": 30.0,
        "revenue_growth_5y_pct": 20.0,
        "free_cash_flow": 100.0,
        "net_income": 120.0,
        "long_term_debt_to_equity": 0.4,
        "shares_insiders_percent": 3.0,
    }
    row.update(overrides)
    return row


def _median_row(industry: str = "Semiconductors") -> dict[str, object]:
    return {
        "industry": industry,
        "operating_margin_pct": 25.0,
        "revenue_growth_5y_pct": 10.0,
    }


def _medians(peers: int = 6, **fields: float) -> dict[str, dict[str, float]]:
    values = {
        "n": peers,
        "operating_margin_pct": 25.0,
        "revenue_growth_5y_pct": 10.0,
    }
    values.update(fields)
    return {"Semiconductors": values}


def _annual_statement(rows: dict[str, list[float | None]]) -> dict[str, object]:
    """Build a parsed-statement shape: newest first, TTM then five fiscal years."""
    periods = [{"key": "TTM", "label": "TTM", "is_ttm": True}]
    periods += [
        {"key": str(year), "label": f"FY{year}", "is_ttm": False}
        for year in range(2026, 2021, -1)
    ]
    return {
        "periods": periods,
        "rows": [
            {"id": key, "label": key, "values": values} for key, values in rows.items()
        ],
    }


def _statements(**overrides: object) -> dict[str, dict[str, object]]:
    statements = {
        "income_annual": _annual_statement(
            {
                "revenue": [110.0, 100.0, 90.0, 80.0, 70.0, 60.0],
                "gp": [55.0, 50.0, 45.0, 40.0, 35.0, 30.0],
                "fcf": [12.0, 10.0, 9.0, 8.0, 7.0, 6.0],
                "dps": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "sharesDiluted": [100.0, 100.0, 99.0, 98.0, 97.0, 96.0],
            }
        ),
        "balance_annual": _annual_statement(
            {
                "sharesOutTotalCommon": [100.0, 100.0, 99.0, 98.0, 97.0, 96.0],
                "treasuryStock": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            }
        ),
    }
    statements.update(overrides)
    return statements


def _quality(row: dict[str, object], statements: object = None, peers: int = 6) -> Gate:
    return quality_gate(row, _medians(peers), statements)  # type: ignore[arg-type]


def test_quality_gate_has_the_ten_spec_checks() -> None:
    gate = _quality(_row(), _statements())
    assert [check.id for check in gate.checks] == [
        "quality.roic_5y",
        "quality.roic_trend",
        "quality.gross_margin_stability",
        "quality.margin_vs_industry",
        "quality.growth_vs_industry",
        "quality.cash_conversion",
        "quality.dilution",
        "quality.shareholder_yield",
        "quality.insider_alignment",
        "quality.leverage_trend",
    ]


def test_quality_roic_threshold_is_inclusive_at_ten_percent() -> None:
    assert _quality(_row(roic_5y_avg_pct=10.0)).checks[0].status == "pass"
    assert _quality(_row(roic_5y_avg_pct=9.99)).checks[0].status == "fail"


def test_quality_missing_field_is_unverified_not_a_pass() -> None:
    gate = _quality(_row(roic_5y_avg_pct=None))
    assert gate.checks[0].status == "unverified"
    assert gate.checks[0].value == "—"


def test_quality_roic_trend_compares_current_with_historical_average() -> None:
    assert _quality(_row(roic_pct=15.0)).checks[1].status == "pass"
    assert _quality(_row(roic_pct=12.0)).checks[1].status == "fail"


def test_quality_cash_conversion_is_unverified_when_profit_is_negative() -> None:
    gate = _quality(_row(net_income=-5.0))
    check = gate.checks[5]
    assert check.status == "unverified"
    assert "not meaningful" in check.value


def test_quality_industry_comparison_needs_five_peers() -> None:
    gate = _quality(_row(), peers=4)
    assert gate.checks[3].status == "unverified"
    assert "fewer than five" in gate.checks[3].value


def test_quality_industry_comparison_uses_the_median() -> None:
    gate = _quality(_row(operating_margin_pct=25.0))
    assert gate.checks[3].status == "pass"
    assert _quality(_row(operating_margin_pct=24.9)).checks[3].status == "fail"


def test_quality_gross_margin_stability_uses_five_fiscal_years() -> None:
    stable = _statements(
        income_annual=_annual_statement(
            {
                "revenue": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
                "gp": [50.0, 50.0, 50.0, 50.0, 50.0, 50.0],
            }
        )
    )
    assert _quality(_row(), stable).checks[2].status == "pass"

    volatile = _statements(
        income_annual=_annual_statement(
            {
                "revenue": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
                "gp": [80.0, 70.0, 60.0, 50.0, 40.0, 30.0],
            }
        )
    )
    assert _quality(_row(), volatile).checks[2].status == "fail"


def test_quality_gross_margin_stability_needs_statement_history() -> None:
    assert _quality(_row()).checks[2].status == "unverified"


def test_quality_dilution_is_unverified_without_share_history() -> None:
    gate = _quality(_row(), {"income_annual": _annual_statement({"revenue": [1.0]})})
    assert gate.checks[6].status == "unverified"


def test_quality_dilution_fails_when_share_count_grows_over_two_percent() -> None:
    growing = _statements(
        balance_annual=_annual_statement(
            {"sharesOutTotalCommon": [112.0, 108.0, 105.0, 102.0, 100.0, 98.0]}
        )
    )
    assert _quality(_row(), growing).checks[6].status == "fail"

    flat = _statements(
        balance_annual=_annual_statement(
            {"sharesOutTotalCommon": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0]}
        )
    )
    assert _quality(_row(), flat).checks[6].status == "pass"


def test_quality_shareholder_yield_fails_when_payouts_exceed_free_cash_flow() -> None:
    generous = _statements(
        income_annual=_annual_statement(
            {
                "revenue": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
                "fcf": [5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
                "dps": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
                "sharesDiluted": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            }
        )
    )
    assert _quality(_row(), generous).checks[7].status == "fail"


def test_quality_insider_alignment_is_pass_or_unverified_only() -> None:
    assert _quality(_row(shares_insiders_percent=1.0)).checks[8].status == "pass"
    assert _quality(_row(shares_insiders_percent=None)).checks[8].status == "unverified"
    assert _quality(_row(shares_insiders_percent=0.0)).checks[8].status == "unverified"


def test_quality_leverage_threshold_is_inclusive_at_one() -> None:
    assert _quality(_row(long_term_debt_to_equity=1.0)).checks[9].status == "pass"
    assert _quality(_row(long_term_debt_to_equity=1.01)).checks[9].status == "fail"


def test_quality_summary_counts_passes_and_names_the_top_failure() -> None:
    gate = _quality(_row(roic_5y_avg_pct=9.0), _statements())
    assert gate.summary.startswith("9/10 quality checks passed")
    assert "ROIC" in gate.summary


def test_industry_medians_group_by_industry_and_count_peers() -> None:
    rows = [
        _median_row(),
        _median_row(),
        _median_row(),
        _median_row(),
        _median_row(),
        {"industry": "Banks", "operating_margin_pct": 40.0},
        {"industry": None, "operating_margin_pct": 99.0},
    ]
    medians = industry_medians(rows)
    assert medians["Semiconductors"]["n"] == 5
    assert medians["Semiconductors"]["operating_margin_pct"] == 25.0
    assert medians["Banks"]["n"] == 1
    assert None not in medians


# ── Task 3: forward gate ─────────────────────────────────────────────


def _forecast(
    revenue_next: float | None = 5.0,
    eps_next: float | None = None,
    actions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    annual: dict[str, object] = {}
    if revenue_next is not None:
        annual["revenueNext"] = {"growth": revenue_next}
    if eps_next is not None:
        annual["epsNext"] = {"growth": eps_next}
    return {"estimates": {"annual": annual}, "ratings": actions or []}


def _quarterly_margins(operating: list[float]) -> dict[str, object]:
    revenue = [100.0] * len(operating)
    periods = [
        {"key": f"Q{index}", "label": f"Q{index}", "is_ttm": False}
        for index in range(len(operating))
    ]
    return {
        "periods": periods,
        "rows": [
            {"id": "revenue", "label": "Revenue", "values": revenue},
            {"id": "opinc", "label": "Operating income", "values": operating},
        ],
    }


def _forward(
    forecast: dict[str, object] | None = None,
    statements: object = None,
    overview: dict[str, object] | None = None,
    hits: tuple[object, ...] = (),
    today: str = "2026-11-23",
) -> Gate:
    return forward_gate(  # type: ignore[arg-type]
        _row(),
        forecast=forecast if forecast is not None else _forecast(),
        statements=statements,
        overview=overview,
        guidance_hits=hits,
        today=today,
    )


def test_forward_gate_has_the_six_spec_checks() -> None:
    gate = _forward()
    assert [check.id for check in gate.checks] == [
        "forward.estimate_growth",
        "forward.revision_direction",
        "forward.margin_trajectory",
        "forward.revenue_trajectory",
        "forward.guidance_present",
        "forward.event_risk",
    ]


def test_forward_estimate_growth_accepts_either_revenue_or_eps() -> None:
    assert _forward(_forecast(revenue_next=5.0)).checks[0].status == "pass"
    assert _forward(_forecast(revenue_next=-5.0)).checks[0].status == "fail"

    up = [{"date": "2026-11-01", "target_now": 120.0, "target_old": 100.0}]
    missing = _forward(
        _forecast(revenue_next=None, actions=up), hits=({"phrase": "outlook"},)
    )
    assert missing.checks[0].status == "unverified"
    assert (
        _forward(_forecast(revenue_next=None, eps_next=3.0)).checks[0].status == "pass"
    )


def test_forward_revision_direction_nets_the_last_ninety_days() -> None:
    up = [{"date": "2026-11-01", "target_now": 120.0, "target_old": 100.0}]
    down = [{"date": "2026-11-01", "target_now": 90.0, "target_old": 100.0}]
    assert _forward(_forecast(actions=up)).checks[1].status == "pass"
    assert _forward(_forecast(actions=down)).checks[1].status == "fail"

    stale = [{"date": "2025-01-01", "target_now": 90.0, "target_old": 100.0}]
    assert _forward(_forecast(actions=stale)).checks[1].status == "unverified"


def test_forward_margin_trajectory_reads_four_quarters() -> None:
    rising = {"income_quarterly": _quarterly_margins([30.0, 28.0, 26.0, 24.0])}
    falling = {"income_quarterly": _quarterly_margins([24.0, 26.0, 28.0, 30.0])}
    assert _forward(statements=rising).checks[2].status == "pass"
    assert _forward(statements=falling).checks[2].status == "fail"
    assert _forward().checks[2].status == "unverified"


def test_forward_revenue_trajectory_compares_with_the_five_year_average() -> None:
    income = _annual_statement(
        {
            "revenue": [140.0, 130.0, 100.0, 90.0, 80.0, 70.0],
        }
    )
    faster = {"income_annual": income}
    assert _forward(statements=faster).checks[3].status == "pass"

    slower_income = _annual_statement(
        {
            "revenue": [110.0, 102.0, 100.0, 90.0, 80.0, 70.0],
        }
    )
    assert (
        _forward(statements={"income_annual": slower_income}).checks[3].status == "fail"
    )


def test_forward_guidance_needs_filing_evidence() -> None:
    assert _forward(hits=({"phrase": "outlook"},)).checks[4].status == "pass"
    assert _forward().checks[4].status == "unverified"


def test_forward_event_risk_uses_the_earnings_date() -> None:
    soon = {"earnings_date": "2026-11-26"}
    later = {"earnings_date": "2026-12-23"}
    assert _forward(overview=soon).checks[5].status == "fail"
    assert _forward(overview=later).checks[5].status == "pass"
    assert _forward().checks[5].status == "unverified"


def test_forward_gate_is_unverified_when_only_some_evidence_is_missing() -> None:
    up = [{"date": "2026-11-01", "target_now": 120.0, "target_old": 100.0}]
    gate = _forward(
        _forecast(revenue_next=None, actions=up), hits=({"phrase": "outlook"},)
    )
    assert gate.checks[0].status == "unverified"
    assert gate.summary != "Trailing evidence only"
    assert gate_status(gate.checks) == "unverified"


def test_backward_only_evidence_fails_the_gate_and_says_so() -> None:
    gate = _forward(_forecast(revenue_next=None))
    trailing = Gate(
        "forward",
        "Forward evidence",
        (gate.checks[0], gate.checks[1], gate.checks[4]),
        gate.summary,
    )
    all_missing = forward_gate(  # type: ignore[arg-type]
        _row(), forecast=None, overview=None, guidance_hits=(), today="2026-11-23"
    )
    assert all_missing.summary == "Trailing evidence only"
    assert gate_status(all_missing.checks) == "fail"
    assert gate_status(trailing.checks) != "pass"
