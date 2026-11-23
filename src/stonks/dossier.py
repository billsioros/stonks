"""Deterministic evidence model for the per-symbol deep dive.

Every verdict in a deep dive is computed here, in Python, from named fields with
fixed thresholds: the model receives the checks and explains them, it never
decides them. Each check is tri-state and fail-closed — a check whose input is
missing is ``unverified``, never ``pass`` — and a gate's status is derived from
its checks rather than assigned.

The module is pure: no I/O, no Streamlit import, no network, so the same inputs
always produce the same dossier.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

Status = Literal["pass", "fail", "unverified", "not_applicable"]


@dataclass(frozen=True)
class Check:
    """One auditable pass/fail question, with the numbers behind the answer."""

    id: str
    label: str
    status: Status
    value: str
    threshold: str
    evidence: str


@dataclass(frozen=True)
class Gate:
    """A group of checks that share a question, plus a one-line verdict."""

    key: str
    label: str
    checks: tuple[Check, ...]
    summary: str


@dataclass(frozen=True)
class Dossier:
    """The full evidence set for one symbol at one point in time."""

    symbol: str
    as_of: str
    gates: tuple[Gate, ...]
    conflicts: tuple[str, ...]
    red_flags: tuple[str, ...]
    provenance: tuple[tuple[str, str, str], ...]
    coverage: float


def gate_status(checks: Sequence[Check]) -> Status:
    """Derive a gate's status from its checks.

    Any failure fails the gate; otherwise anything unverifiable leaves it
    unverified. A gate whose checks all legitimately do not apply is
    ``not_applicable``, while a gate with no checks at all is ``unverified``: an
    empty gate proves nothing and must not read as a pass.
    """
    if not checks:
        return "unverified"
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        return "fail"
    if "unverified" in statuses:
        return "unverified"
    if any(check.status == "pass" for check in checks):
        return "pass"
    return "not_applicable"


def coverage(gates: Iterable[Gate]) -> float:
    """Fraction of applicable checks that passed, across every gate.

    Checks that do not apply are excluded from both numerator and denominator,
    so a symbol with many inapplicable checks is neither rewarded nor punished.
    """
    applicable = [
        check
        for gate in gates
        for check in gate.checks
        if check.status != "not_applicable"
    ]
    if not applicable:
        return 0.0
    passed = sum(1 for check in applicable if check.status == "pass")
    return passed / len(applicable)


# ── Quantitative thresholds ──────────────────────────────────────────
# Each constant is a judgement call, stated once here so tests pin the trade-off
# rather than a magic number buried in a comparison.
ROIC_MIN_PCT = 10.0
GROSS_MARGIN_STDEV_MAX_PP = 3.0
MIN_INDUSTRY_PEERS = 5
CASH_CONVERSION_MIN = 0.8
DILUTION_MAX_CAGR_PCT = 2.0
LEVERAGE_MAX = 1.0
DASH = "—"


def _num(value: object) -> float | None:
    """Read a number from a stored field, returning ``None`` when it is not one."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            parsed = float(value.strip().replace(",", "").rstrip("%"))
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _status_from(ok: bool | None) -> Status:
    """Tri-state from a comparison: ``None`` means the check could not be made."""
    if ok is None:
        return "unverified"
    return "pass" if ok else "fail"


def _annual_series(
    statement: Mapping[str, Any] | None, row_id: str
) -> list[float | None]:
    """One line item's fiscal-year values, newest first, excluding the TTM column."""
    if not statement:
        return []
    periods = statement.get("periods") or []
    keep = [
        index
        for index, period in enumerate(periods)
        if isinstance(period, Mapping) and not period.get("is_ttm")
    ]
    for row in statement.get("rows") or []:
        if isinstance(row, Mapping) and row.get("id") == row_id:
            values = row.get("values") or []
            return [_num(values[i]) if i < len(values) else None for i in keep]
    return []


def _statement(statements: object, key: str) -> Mapping[str, Any] | None:
    """Fetch one parsed statement from the optional bundle."""
    if isinstance(statements, Mapping):
        value = statements.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def industry_medians(
    rows: Iterable[Mapping[str, Any]],
    fields: Sequence[str] = ("operating_margin_pct", "revenue_growth_5y_pct"),
) -> dict[str, dict[str, float]]:
    """Per-industry medians for the snapshot, with the number of peers behind each.

    A median from fewer than five peers is too noisy to judge a company against,
    which is why the count travels with the numbers instead of being dropped.
    """
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        industry = row.get("industry")
        if isinstance(industry, str) and industry.strip():
            groups.setdefault(industry, []).append(row)

    medians: dict[str, dict[str, float]] = {}
    for industry, peers in groups.items():
        entry: dict[str, float] = {"n": float(len(peers))}
        for field in fields:
            values = [
                value for row in peers if (value := _num(row.get(field))) is not None
            ]
            if values:
                entry[field] = statistics.median(values)
        medians[industry] = entry
    return medians


def quality_gate(
    row: Mapping[str, Any],
    medians: Mapping[str, Mapping[str, float]] | None = None,
    statements: object = None,
) -> Gate:
    """Gate 1: does the business clear a fixed quality bar.

    Every check reads a named field and compares it with a constant in this
    module; nothing is inferred and nothing missing becomes a pass. Statement
    history is optional: without it the stability, dilution and payout checks are
    ``unverified`` rather than guessed from a single period.
    """
    income = _statement(statements, "income_annual")
    balance = _statement(statements, "balance_annual")
    checks: list[Check] = []

    roic_5y = _num(row.get("roic_5y_avg_pct"))
    checks.append(
        Check(
            "quality.roic_5y",
            "ROIC (5y average) above 10%",
            _status_from(None if roic_5y is None else roic_5y >= ROIC_MIN_PCT),
            DASH if roic_5y is None else f"{roic_5y:.1f}%",
            f">= {ROIC_MIN_PCT:.1f}%",
            "screener.roic_5y_avg_pct",
        )
    )

    roic_now = _num(row.get("roic_pct"))
    trend_ok: bool | None = None
    if roic_now is not None and roic_5y is not None:
        trend_ok = roic_now >= roic_5y
    checks.append(
        Check(
            "quality.roic_trend",
            "Returns are not deteriorating",
            _status_from(trend_ok),
            DASH
            if roic_now is None or roic_5y is None
            else f"{roic_now:.1f}% vs {roic_5y:.1f}%",
            "current >= 5y average",
            "screener.roic_pct, screener.roic_5y_avg_pct",
        )
    )

    revenue = _annual_series(income, "revenue")
    gross_profit = _annual_series(income, "gp")
    margins = [
        gross / sales * 100.0
        for sales, gross in zip(revenue, gross_profit, strict=False)
        if sales and gross is not None and sales > 0
    ]
    if len(margins) >= 3:
        stdev = statistics.pstdev(margins)
        stability_ok: bool | None = stdev <= GROSS_MARGIN_STDEV_MAX_PP
        stability_value = f"stdev {stdev:.1f}pp over {len(margins)}y"
    else:
        stability_ok = None
        stability_value = "no five-year margin history"
    checks.append(
        Check(
            "quality.gross_margin_stability",
            "Gross margin is stable",
            _status_from(stability_ok),
            stability_value,
            f"stdev <= {GROSS_MARGIN_STDEV_MAX_PP:.1f}pp",
            "income_annual.gp / income_annual.revenue",
        )
    )

    industry = row.get("industry")
    peers = medians.get(industry) if isinstance(industry, str) and medians else None
    peer_count = int(peers.get("n", 0)) if peers else 0

    operating_margin = _num(row.get("operating_margin_pct"))
    industry_margin = _num(peers.get("operating_margin_pct")) if peers else None
    margin_ok: bool | None = None
    if peer_count < MIN_INDUSTRY_PEERS:
        margin_value = f"fewer than five peers ({peer_count})"
    elif operating_margin is None or industry_margin is None:
        margin_value = "no peer median"
    else:
        margin_ok = operating_margin >= industry_margin
        margin_value = f"{operating_margin:.1f}% vs {industry_margin:.1f}%"
    checks.append(
        Check(
            "quality.margin_vs_industry",
            "Operating margin at or above its industry",
            _status_from(margin_ok),
            margin_value,
            ">= industry median",
            "screener.operating_margin_pct, industry median",
        )
    )

    growth = _num(row.get("revenue_growth_5y_pct"))
    industry_growth = _num(peers.get("revenue_growth_5y_pct")) if peers else None
    growth_ok: bool | None = None
    if peer_count < MIN_INDUSTRY_PEERS:
        growth_value = f"fewer than five peers ({peer_count})"
    elif growth is None or industry_growth is None:
        growth_value = "no peer median"
    else:
        growth_ok = growth >= industry_growth
        growth_value = f"{growth:.1f}% vs {industry_growth:.1f}%"
    checks.append(
        Check(
            "quality.growth_vs_industry",
            "Revenue growth at or above its industry",
            _status_from(growth_ok),
            growth_value,
            ">= industry median",
            "screener.revenue_growth_5y_pct, industry median",
        )
    )

    free_cash_flow = _num(row.get("free_cash_flow"))
    net_income = _num(row.get("net_income"))
    conversion_ok: bool | None = None
    if net_income is not None and net_income <= 0:
        conversion_value = "not meaningful (net income <= 0)"
    elif free_cash_flow is None or net_income is None:
        conversion_value = DASH
    else:
        ratio = free_cash_flow / net_income
        conversion_ok = ratio >= CASH_CONVERSION_MIN
        conversion_value = f"{ratio:.2f} vs {CASH_CONVERSION_MIN:.2f}"
    checks.append(
        Check(
            "quality.cash_conversion",
            "Profit converts to cash",
            _status_from(conversion_ok),
            conversion_value,
            f">= {CASH_CONVERSION_MIN:.2f}",
            "screener.free_cash_flow / screener.net_income",
        )
    )

    shares = [
        value for value in _annual_series(balance, "sharesOutTotalCommon") if value
    ]
    if not shares:
        shares = [value for value in _annual_series(income, "sharesDiluted") if value]
    dilution_ok: bool | None = None
    if len(shares) < 2:
        dilution_value = "no share-count history"
    else:
        years = len(shares) - 1
        cagr = ((shares[0] / shares[-1]) ** (1 / years) - 1) * 100.0
        dilution_ok = cagr <= DILUTION_MAX_CAGR_PCT
        dilution_value = f"share CAGR {cagr:.1f}%"
    checks.append(
        Check(
            "quality.dilution",
            "Management does not dilute",
            _status_from(dilution_ok),
            dilution_value,
            f"covering <= {DILUTION_MAX_CAGR_PCT:.1f}% a year",
            "balance_annual.sharesOutTotalCommon",
        )
    )

    dividends_per_share = _annual_series(income, "dps")
    diluted_shares = _annual_series(income, "sharesDiluted")
    statement_fcf = _annual_series(income, "fcf")
    treasury = _annual_series(balance, "treasuryStock")
    payout_ok: bool | None = None
    if dividends_per_share and diluted_shares and dividends_per_share[0] is not None:
        shares_out = diluted_shares[0]
        if shares_out is None:
            payout_value = "no share count for the payout"
        else:
            dividends = abs(dividends_per_share[0]) * shares_out
            buybacks = 0.0
            if (
                len(treasury) >= 2
                and treasury[0] is not None
                and treasury[1] is not None
            ):
                buybacks = max(treasury[0] - treasury[1], 0.0)
            cash = (
                statement_fcf[0]
                if statement_fcf and statement_fcf[0] is not None
                else None
            )
            if cash is None:
                cash = free_cash_flow
            if cash is None:
                payout_value = "no free-cash-flow history"
            else:
                payout = dividends + buybacks
                payout_ok = abs(payout) <= cash
                payout_value = f"{payout:,.0f} paid vs {cash:,.0f} free cash flow"
    else:
        payout_value = "no dividend history"
    checks.append(
        Check(
            "quality.shareholder_yield",
            "Capital returned within free cash flow",
            _status_from(payout_ok),
            payout_value,
            "payout <= free cash flow",
            "income_annual.dps, income_annual.fcf, balance_annual.treasuryStock",
        )
    )

    insiders = _num(row.get("shares_insiders_percent"))
    insider_ok: bool | None = None
    if insiders is not None and insiders > 0:
        insider_ok = True
    checks.append(
        Check(
            "quality.insider_alignment",
            "Insiders own a stake",
            _status_from(insider_ok),
            DASH if insiders is None else f"{insiders:.2f}%",
            "> 0% (informational)",
            "screener.shares_insiders_percent",
        )
    )

    leverage = _num(row.get("long_term_debt_to_equity"))
    checks.append(
        Check(
            "quality.leverage_trend",
            "Long-term leverage is moderate",
            _status_from(None if leverage is None else leverage <= LEVERAGE_MAX),
            DASH if leverage is None else f"{leverage:.2f}",
            f"<= {LEVERAGE_MAX:.2f}",
            "screener.long_term_debt_to_equity",
        )
    )

    return Gate(
        key="quality",
        label="Business quality",
        checks=tuple(checks),
        summary=_gate_summary("quality", checks),
    )


def _gate_summary(name: str, checks: Sequence[Check]) -> str:
    """Summarise a gate: how many checks passed and which one failed first."""
    passed = sum(1 for check in checks if check.status == "pass")
    summary = f"{passed}/{len(checks)} {name} checks passed"
    failure = next((check for check in checks if check.status == "fail"), None)
    if failure is not None:
        return (
            f"{summary}; fails {failure.label} ({failure.value} vs {failure.threshold})"
        )
    unverified = sum(1 for check in checks if check.status == "unverified")
    if unverified:
        return f"{summary}; {unverified} unverified"
    return summary
