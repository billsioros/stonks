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
from dataclasses import field as dataclass_field
from datetime import date, datetime
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
    """A group of checks that share a question, plus a one-line verdict.

    ``conflicts`` carries structured cross-check disagreements that do not fit
    inside a single ``Check``, for the dossier to merge into its conflict list.
    """

    key: str
    label: str
    checks: tuple[Check, ...]
    summary: str
    conflicts: tuple[str, ...] = ()


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


@dataclass(frozen=True)
class FilingEvidence:
    """Fetched filing facts and phrase hits, supplied to the pure filing gate.

    The dossier owns this shape so it never imports an I/O module. ``reason`` is
    set when SEC data could not be fetched or trusted; in that case the gate
    reports one unverified check rather than pretending the filings are clean.
    """

    cik: str | None = None
    facts: Mapping[str, Any] = dataclass_field(default_factory=dict)
    hits: tuple[Mapping[str, Any], ...] = ()
    latest_10k: str | None = None
    latest_10q: str | None = None
    guidance_hits: tuple[Mapping[str, Any], ...] = ()
    reason: str | None = None

    @classmethod
    def empty(cls) -> FilingEvidence:
        """Evidence placeholder for callers that supplied no filing evidence."""
        return cls(reason="No filing evidence supplied")


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


PORTFOLIO_SECTOR_MAX_PCT = 25.0


def fit_gate(
    symbol: str,
    row: Mapping[str, Any],
    watchlist: Iterable[Mapping[str, Any]] | None,
) -> Gate:
    """Equal-weight watchlist proxy for exposure and sector concentration."""
    if watchlist is None:
        return Gate(
            "fit",
            "Portfolio fit",
            (
                Check(
                    "fit.portfolio",
                    "Holding context",
                    "not_applicable",
                    DASH,
                    "Portfolio supplied",
                    "No portfolio supplied",
                ),
            ),
            "No portfolio supplied",
        )

    entries = list(watchlist)
    if not entries:
        return Gate(
            "fit",
            "Portfolio fit",
            (
                Check(
                    "fit.watchlist_presence",
                    "Holding context",
                    "not_applicable",
                    "empty watchlist",
                    "Symbol present in watchlist",
                    "watchlist.symbol",
                ),
                Check(
                    "fit.sector_concentration",
                    "Watchlist sector concentration",
                    "not_applicable",
                    "empty watchlist",
                    f"<= {PORTFOLIO_SECTOR_MAX_PCT:.0f}% of watchlist",
                    "equal-weight watchlist proxy, screener.industry",
                ),
            ),
            "No holdings supplied",
        )

    symbols = {str(entry.get("symbol", "")).upper() for entry in entries}
    presence_ok = symbol.upper() in symbols
    raw_sector = row.get("industry")
    symbol_sector = (
        str(raw_sector).casefold()
        if isinstance(raw_sector, str) and raw_sector.strip()
        else ""
    )
    sectors = [
        str(item).casefold()
        for entry in entries
        if (item := entry.get("industry")) and isinstance(item, str) and item.strip()
    ]
    sector_ok: bool | None = None
    if not symbol_sector:
        concentration_value = "symbol industry unavailable"
    elif not sectors:
        concentration_value = "watchlist industries unavailable"
    else:
        share = (
            sum(1 for item in sectors if item == symbol_sector) / len(sectors) * 100.0
        )
        sector_ok = share <= PORTFOLIO_SECTOR_MAX_PCT
        concentration_value = f"{share:.0f}% of watchlist in {raw_sector}"
    concentration = Check(
        "fit.sector_concentration",
        "Watchlist sector concentration",
        _status_from(sector_ok),
        concentration_value,
        f"<= {PORTFOLIO_SECTOR_MAX_PCT:.0f}% of watchlist",
        "equal-weight watchlist proxy, screener.industry",
    )
    presence = Check(
        "fit.watchlist_presence",
        "Holding context",
        _status_from(presence_ok),
        "on watchlist" if presence_ok else "not on watchlist",
        "Symbol present in watchlist",
        "watchlist.symbol",
    )
    return Gate(
        "fit",
        "Portfolio fit",
        (presence, concentration),
        _gate_summary("fit", (presence, concentration)),
    )


DECISION_SUMMARY_LIMIT = 6


def decision_summary(dossier: Dossier) -> dict[str, Any]:
    """Facts a reader would need before treating a dossier as actionable.

    This is deliberately not a verdict: it turns existing checks into the open
    questions, unresolved evidence and freshness a human has to weigh.
    """
    checks = [check for gate in dossier.gates for check in gate.checks]
    unknown = [check for check in checks if check.status == "unverified"]
    unresolved = [check for check in checks if check.status in {"fail", "unverified"}]
    freshness = next(
        (check.value for check in checks if check.id == "filings.freshness"),
        "not available",
    )
    return {
        "coverage": dossier.coverage,
        "freshness": freshness,
        "unknowns": tuple(
            f"{check.id}: {check.value}" for check in unknown[:DECISION_SUMMARY_LIMIT]
        ),
        "changes": tuple(
            f"{check.id} — {check.threshold}"
            for check in unresolved[:DECISION_SUMMARY_LIMIT]
        ),
    }


# ── Quantitative thresholds ──────────────────────────────────────────
# Each constant is a judgement call, stated once here so tests pin the trade-off
# rather than a magic number buried in a comparison.
ROIC_MIN_PCT = 10.0
GROSS_MARGIN_LEVEL_MIN_PCT = 30.0
GROSS_MARGIN_STDEV_MAX_PP = 3.0
MIN_INDUSTRY_PEERS = 5
CASH_CONVERSION_MIN = 0.8
FCF_MARGIN_MIN_PCT = 5.0
FCF_STABILITY_YEARS = 5
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


def _check_status(checks: Sequence[Check], check_id: str) -> Status:
    """Read a check by stable ID, not by its position in the gate."""
    return next(
        (check.status for check in checks if check.id == check_id), "unverified"
    )


def _replace_check(
    checks: list[Check], check_id: str, *, status: Status, value: str
) -> None:
    """Update one check by stable ID, preserving its label and threshold."""
    for index, check in enumerate(checks):
        if check.id == check_id:
            checks[index] = Check(
                check.id, check.label, status, value, check.threshold, check.evidence
            )
            return


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

    persistence_ok: bool | None = None
    if roic_now is not None and roic_5y is not None:
        persistence_ok = roic_now >= ROIC_MIN_PCT and roic_5y >= ROIC_MIN_PCT
    checks.append(
        Check(
            "quality.roic_persistence",
            "Returns stay above the quality bar",
            _status_from(persistence_ok),
            DASH
            if roic_now is None or roic_5y is None
            else f"current {roic_now:.1f}%, 5y {roic_5y:.1f}%",
            f"current and 5y >= {ROIC_MIN_PCT:.1f}%",
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
    if len(margins) >= 5:
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

    gross_margin = _num(row.get("gross_margin_pct"))
    checks.append(
        Check(
            "quality.gross_margin_level",
            "Gross margin shows pricing power",
            _status_from(
                None
                if gross_margin is None
                else gross_margin >= GROSS_MARGIN_LEVEL_MIN_PCT
            ),
            DASH if gross_margin is None else f"{gross_margin:.1f}%",
            f">= {GROSS_MARGIN_LEVEL_MIN_PCT:.1f}%",
            "screener.gross_margin_pct",
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

    fcf_margin = _num(row.get("fcf_margin_pct"))
    checks.append(
        Check(
            "quality.fcf_margin",
            "Free cash flow margin is healthy",
            _status_from(
                None if fcf_margin is None else fcf_margin >= FCF_MARGIN_MIN_PCT
            ),
            DASH if fcf_margin is None else f"{fcf_margin:.1f}%",
            f">= {FCF_MARGIN_MIN_PCT:.1f}%",
            "screener.fcf_margin_pct",
        )
    )

    fcf_series = _annual_series(income, "fcf")[:FCF_STABILITY_YEARS]
    if len(fcf_series) < FCF_STABILITY_YEARS or any(
        value is None for value in fcf_series
    ):
        fcf_stability_ok: bool | None = None
        fcf_stability_value = "missing FCF year in five-year window"
    else:
        values = [value for value in fcf_series if value is not None]
        fcf_stability_ok = all(value > 0 for value in values)
        positive = sum(1 for value in values if value > 0)
        fcf_stability_value = f"{positive}/{len(values)} positive FCF years"
    checks.append(
        Check(
            "quality.fcf_stability",
            "Free cash flow stays positive",
            _status_from(fcf_stability_ok),
            fcf_stability_value,
            f"positive in {FCF_STABILITY_YEARS} fiscal years",
            "income_annual.fcf",
        )
    )

    shares = [
        value for value in _annual_series(balance, "sharesOutTotalCommon") if value
    ]
    if not shares:
        shares = [value for value in _annual_series(income, "sharesDiluted") if value]
    dilution_ok: bool | None = None
    if len(shares) < 5:
        dilution_value = "no five-year share history"
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
            has_buyback_history = (
                len(treasury) >= 2
                and treasury[0] is not None
                and treasury[1] is not None
            )
            if not has_buyback_history:
                # Without treasury history a dividend-only "pass" could hide a
                # large buyback; missing input must stay unverified.
                payout_value = "no buyback history"
            else:
                latest, previous = treasury[0], treasury[1]
                buybacks = (
                    max(latest - previous, 0.0)
                    if latest is not None and previous is not None
                    else 0.0
                )
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


# ── Forward evidence ─────────────────────────────────────────────────
REVISION_WINDOW_DAYS = 90
EVENT_RISK_DAYS = 7
GUIDANCE_FRESH_DAYS = 120
QUARTERS_FOR_ACCELERATION = 5
TRAILING_ONLY = "Trailing evidence only"


def _as_date(value: object) -> date | None:
    """Parse an ISO or provider-style date, ignoring anything unparsable."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for pattern in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _isdigit_sign(value: float) -> int:
    """Direction of a change, so analyst actions can be netted."""
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _quarterly_acceleration(
    statement: Mapping[str, Any] | None, row_id: str, baseline: float | None
) -> tuple[bool | None, str]:
    """Compare the latest quarter's YoY growth with a long-run growth average."""
    values = _annual_series(statement, row_id)
    if len(values) < QUARTERS_FOR_ACCELERATION:
        return None, "fewer than five comparable quarters"
    latest, year_ago = values[0], values[QUARTERS_FOR_ACCELERATION - 1]
    if latest is None or year_ago is None or latest <= 0 or year_ago <= 0:
        return None, "no positive quarterly base"
    if baseline is None:
        return None, "no five-year growth baseline"
    yoy = (latest / year_ago - 1.0) * 100.0
    return yoy > baseline, f"{yoy:+.1f}% YoY vs {baseline:+.1f}% 5y average"


def forward_gate(
    row: Mapping[str, Any],
    *,
    forecast: Mapping[str, Any] | None = None,
    statements: object = None,
    overview: Mapping[str, Any] | None = None,
    guidance_hits: Sequence[object] = (),
    today: object = None,
) -> Gate:
    """Gate 2: is there evidence about where the business is going.

    Trailing growth says where a company has been. This gate only passes checks
    on evidence that points forward: consensus estimates, analyst revisions in
    the last quarter, the quarterly margin slope, quarterly growth acceleration,
    guidance in a filing and the distance to the next earnings date. If none of
    the three leading indicators is available the gate is an explicit failure
    labelled "Trailing evidence only", so a memo cannot quietly extrapolate
    history into a thesis.
    """
    today_date = _as_date(today) or date.today()
    checks: list[Check] = []

    annual = (forecast or {}).get("estimates") or {}
    annual = annual.get("annual") if isinstance(annual, Mapping) else None
    growths: dict[str, float] = {}
    if isinstance(annual, Mapping):
        for key, label in (("revenueNext", "revenue"), ("epsNext", "EPS")):
            entry = annual.get(key)
            growth = _num(entry.get("growth")) if isinstance(entry, Mapping) else None
            if growth is not None:
                growths[label] = growth
    estimate_ok: bool | None = None
    if growths:
        estimate_ok = any(growth > 0 for growth in growths.values())
    estimate_value = (
        ", ".join(f"{label} {growth:+.1f}%" for label, growth in growths.items())
        if growths
        else "no consensus estimate"
    )
    checks.append(
        Check(
            "forward.estimate_growth",
            "Analysts expect growth",
            _status_from(estimate_ok),
            estimate_value,
            "next-year consensus growth > 0%",
            "forecast.estimates.annual",
        )
    )

    ratings = (forecast or {}).get("ratings") or []
    net = 0
    counted = 0
    for rating in ratings:
        if not isinstance(rating, Mapping):
            continue
        when = _as_date(rating.get("date"))
        now_target = _num(rating.get("target_now"))
        old_target = _num(rating.get("target_old"))
        if when is None or now_target is None or old_target is None:
            continue
        if (today_date - when).days > REVISION_WINDOW_DAYS:
            continue
        counted += 1
        net += _isdigit_sign(now_target - old_target)
    revision_ok: bool | None = net >= 0 if counted else None
    checks.append(
        Check(
            "forward.revision_direction",
            "Estimates are not being cut",
            _status_from(revision_ok),
            f"net {net:+d} over {counted} actions"
            if counted
            else "no recent analyst actions",
            "net revisions >= 0 in 90 days",
            "forecast.ratings",
        )
    )

    quarterly = _statement(statements, "income_quarterly")
    operating = _annual_series(quarterly, "opinc")
    revenue_q = _annual_series(quarterly, "revenue")
    quarterly_margins = [
        income / sales * 100.0
        for sales, income in zip(revenue_q, operating, strict=False)
        if sales and income is not None and sales > 0
    ][:4]
    margin_ok: bool | None = None
    if len(quarterly_margins) < 4:
        margin_value = "fewer than four quarters"
    else:
        slope = (quarterly_margins[0] - quarterly_margins[3]) / 3.0
        margin_ok = slope > 0
        margin_value = f"{slope:+.2f}pp per quarter"
    checks.append(
        Check(
            "forward.margin_trajectory",
            "Margins are expanding",
            _status_from(margin_ok),
            margin_value,
            "four-quarter slope > 0",
            "income_quarterly.opinc / income_quarterly.revenue",
        )
    )

    income_annual = _statement(statements, "income_annual")
    revenue_a = [value for value in _annual_series(income_annual, "revenue") if value]
    growth_5y = _num(row.get("revenue_growth_5y_pct"))
    trajectory_ok: bool | None = None
    if len(revenue_a) < 2 or growth_5y is None:
        trajectory_value = "no year-over-year history"
    else:
        latest = (revenue_a[0] / revenue_a[1] - 1) * 100.0
        trajectory_ok = latest >= growth_5y
        trajectory_value = f"{latest:.1f}% vs {growth_5y:.1f}% 5y average"
    checks.append(
        Check(
            "forward.revenue_trajectory",
            "Top line is not decelerating",
            _status_from(trajectory_ok),
            trajectory_value,
            "latest YoY >= 5y average",
            "income_annual.revenue, screener.revenue_growth_5y_pct",
        )
    )

    guidance_dates = [
        filed
        for hit in guidance_hits
        if isinstance(hit, Mapping) and (filed := _as_date(hit.get("filing_date")))
    ]
    future_dates = [filed for filed in guidance_dates if filed > today_date]
    guidance_dates = [filed for filed in guidance_dates if filed <= today_date]
    if not guidance_hits:
        guidance_ok: bool | None = None
        guidance_value = "no filing evidence"
    elif not guidance_dates:
        guidance_ok = None
        guidance_value = (
            "future filing date"
            if future_dates
            else "guidance hits without filing dates"
        )
    else:
        ages = [(today_date - filed).days for filed in guidance_dates]
        newest = min(ages)
        if newest <= GUIDANCE_FRESH_DAYS:
            guidance_ok = True
            guidance_value = f"{len(guidance_dates)} filing(s) mention guidance, newest {newest}d old"
        else:
            guidance_ok = False
            guidance_value = f"guidance last seen {newest}d ago (stale)"
    checks.append(
        Check(
            "forward.guidance_present",
            "Management has guided recently",
            _status_from(guidance_ok),
            guidance_value,
            f"guidance/outlook in a filing within {GUIDANCE_FRESH_DAYS} days",
            "filings.guidance",
        )
    )

    earnings = _as_date((overview or {}).get("earnings_date"))
    event_ok: bool | None = None
    if earnings is None:
        event_value = "no earnings date"
    else:
        days_ahead = (earnings - today_date).days
        event_ok = days_ahead > EVENT_RISK_DAYS
        event_value = f"earnings in {days_ahead} days"
    checks.append(
        Check(
            "forward.event_risk",
            "No imminent binary event",
            _status_from(event_ok),
            event_value,
            f"earnings > {EVENT_RISK_DAYS} days away",
            "overview.earnings_date",
        )
    )

    revenue_ok, revenue_value = _quarterly_acceleration(
        quarterly, "revenue", _num(row.get("revenue_growth_5y_pct"))
    )
    checks.append(
        Check(
            "forward.revenue_acceleration",
            "Recent revenue growth is accelerating",
            _status_from(revenue_ok),
            revenue_value,
            "latest quarter YoY > 5y revenue growth average",
            "income_quarterly.revenue, screener.revenue_growth_5y_pct",
        )
    )
    eps_ok, eps_value = _quarterly_acceleration(
        quarterly, "eps", _num(row.get("eps_growth_5y_pct"))
    )
    checks.append(
        Check(
            "forward.eps_acceleration",
            "Recent earnings growth is accelerating",
            _status_from(eps_ok),
            eps_value,
            "latest quarter YoY > 5y EPS growth average",
            "income_quarterly.eps, screener.eps_growth_5y_pct",
        )
    )

    leading = tuple(
        _check_status(checks, check_id)
        for check_id in (
            "forward.estimate_growth",
            "forward.revision_direction",
            "forward.guidance_present",
        )
    )
    if all(status in {"unverified", "fail"} for status in leading):
        _replace_check(
            checks,
            "forward.estimate_growth",
            status="fail",
            value="no forward estimate, revision or guidance",
        )
        summary = TRAILING_ONLY
    else:
        summary = _gate_summary("forward", checks)

    return Gate(
        key="forward",
        label="Forward evidence",
        checks=tuple(checks),
        summary=summary,
    )


# ── Filing evidence ───────────────────────────────────────────────────
# Phrases and thresholds are named here, next to the deterministic gate, so the
# I/O layer sweeps exactly the phrases the gate reports.
RED_FLAG_PHRASES = (
    "material weakness",
    "going concern",
    "covenant",
    "restatement",
    "SEC investigation",
)
INFORMATIONAL_PHRASES = (
    "customer concentration",
    "litigation",
    "regulatory",
    "related party",
    "off-balance sheet",
    "impairment",
    "cybersecurity incident",
    "internal control",
    "supplier concentration",
    "competition",
    "pricing pressure",
)
GUIDANCE_PHRASES = ("guidance", "outlook")
FRESHNESS_MAX_DAYS = {"10-K": 400, "10-Q": 120}
PHRASE_NOTE = "phrase search is evidence, not proof"
ABSENCE_NOTE = "absence of a phrase is not proof"


def _phrase_check_id(phrase: str) -> str:
    return f"filings.{phrase.casefold().replace(' ', '_')}"


def _matching_hits(
    hits: Iterable[Mapping[str, Any]], phrase: str
) -> list[Mapping[str, Any]]:
    wanted = phrase.casefold()
    return [
        hit
        for hit in hits
        if isinstance(hit, Mapping)
        and str(hit.get("phrase") or "").casefold() == wanted
    ]


def _phrase_check(
    phrase: str, hits: Iterable[Mapping[str, Any]], *, informational: bool = False
) -> Check:
    """One phrase search: red-flag phrases pass or fail, the rest never pass.

    A hit is evidence to read, not a verdict about the business, so every hit
    carries its filing date and link; no prose is scored.
    """
    matching = _matching_hits(hits, phrase)
    count = matching[0].get("count", 0) if matching else 0
    value = f"{count} hit(s)" if matching else "no hits"
    links = ", ".join(_hit_line(hit) for hit in matching)
    if informational:
        status: Status = "unverified"
        evidence = f"{phrase}: {PHRASE_NOTE}; {links or 'no hits'}"
        threshold = PHRASE_NOTE
    elif matching:
        status = "fail"
        evidence = f"{phrase}: {links}"
        threshold = "no phrase hits in 10-K/10-Q"
    else:
        status = "pass"
        evidence = f"{phrase}: {ABSENCE_NOTE}"
        threshold = "no phrase hits in 10-K/10-Q"
    return Check(
        _phrase_check_id(phrase),
        f"Filing mentions '{phrase}'",
        status,
        value,
        threshold,
        evidence,
    )


def _freshness_check(evidence: FilingEvidence, today: date) -> Check:
    """Compare the newest 10-K and 10-Q filing dates with fixed day limits."""
    parts: list[str] = []
    outcomes: list[bool | None] = []
    for form, raw in (("10-K", evidence.latest_10k), ("10-Q", evidence.latest_10q)):
        limit = FRESHNESS_MAX_DAYS[form]
        filed = _as_date(raw)
        if filed is None:
            parts.append(f"{form}: no filing date")
            outcomes.append(None)
            continue
        age = (today - filed).days
        outcomes.append(age <= limit)
        parts.append(f"{form} filed {filed.isoformat()} ({age}d old)")
    # A known failure outranks an unknown date: a stale filing is stale even
    # when the other form's date is missing.
    if any(outcome is False for outcome in outcomes):
        status: Status = "fail"
    elif any(outcome is None for outcome in outcomes):
        status = "unverified"
    else:
        status = "pass"
    value = "; ".join(parts)
    if status == "fail":
        value += "; stale filings"
    return Check(
        "filings.freshness",
        "Primary filings are current",
        status,
        value,
        f"10-K <= {FRESHNESS_MAX_DAYS['10-K']} days, "
        f"10-Q <= {FRESHNESS_MAX_DAYS['10-Q']} days",
        "companyfacts 10-K/10-Q filing dates",
    )


def filing_gate(
    row: Mapping[str, Any],
    statements: Mapping[str, Any],
    evidence: FilingEvidence,
    *,
    today: object = None,
) -> Gate:
    """Gate 3: verify vendor figures against filings and sweep them for red flags."""
    if evidence.reason:
        check = Check(
            "filings.primary",
            "Primary filing evidence",
            "unverified",
            evidence.reason,
            "Verified filing text",
            evidence.reason,
        )
        return Gate("filings", "Filings & guidance", (check,), evidence.reason)

    # Imported here rather than at module scope: edgar_parse imports Check from
    # this module, and the dossier itself stays free of I/O dependencies.
    from stonks.edgar_parse import filing_checks

    facts = evidence.facts if isinstance(evidence.facts, Mapping) else {}
    checks, conflicts = filing_checks(row, statements, facts)
    checks.extend(_phrase_check(phrase, evidence.hits) for phrase in RED_FLAG_PHRASES)
    checks.append(_freshness_check(evidence, _as_date(today) or date.today()))
    checks.extend(
        _phrase_check(phrase, evidence.hits, informational=True)
        for phrase in INFORMATIONAL_PHRASES
    )
    return Gate(
        "filings",
        "Filings & guidance",
        tuple(checks),
        _gate_summary("filings", checks),
        tuple(conflicts),
    )


def _hit_line(hit: Mapping[str, Any]) -> str:
    """One dated, linked phrase hit with its filing identity and excerpt."""
    parts = [
        str(hit.get("phrase") or "phrase"),
        str(hit.get("form") or "unknown form"),
        str(hit.get("filing_date") or "unknown date"),
        str(hit.get("accession") or "unknown accession"),
        str(hit.get("url") or "no filing link"),
    ]
    snippet = str(hit.get("snippet") or "").strip()
    if snippet:
        parts.append(f'"{snippet}"')
    return " ".join(parts)


def build_dossier(
    symbol: str,
    *,
    row: Mapping[str, Any] | None = None,
    forecast: Mapping[str, Any] | None = None,
    statements: Mapping[str, Any] | None = None,
    overview: Mapping[str, Any] | None = None,
    peers: Iterable[Mapping[str, Any]] | None = None,
    as_of: str | None = None,
    today: object = None,
    filing_evidence: FilingEvidence | None = None,
    guidance_hits: Sequence[Mapping[str, Any]] = (),
    watchlist: Iterable[Mapping[str, Any]] | None = None,
) -> Dossier:
    """Assemble the gates available today into one deterministic dossier.

    Filing evidence is supplied by the caller, together with its guidance hits
    for the forward gate. A watchlist, when supplied, is used as a labelled
    equal-weight exposure proxy; without it the fit gate stays not applicable.
    Nothing here performs I/O.
    """
    snapshot = row or {}
    evidence = filing_evidence or FilingEvidence.empty()
    medians = industry_medians(peers) if peers is not None else None
    filings = filing_gate(snapshot, statements or {}, evidence, today=today)
    gates = [
        quality_gate(snapshot, medians=medians, statements=statements),
        forward_gate(
            snapshot,
            forecast=forecast,
            statements=statements,
            overview=overview,
            guidance_hits=guidance_hits,
            today=today,
        ),
        filings,
        fit_gate(symbol, snapshot, watchlist),
    ]
    stamp = as_of or "unknown"
    provenance: list[tuple[str, str, str]] = [
        ("screener", "stored row snapshot", stamp)
    ]
    if evidence.cik:
        filing_dates = [
            (parsed, raw)
            for raw in (evidence.latest_10k, evidence.latest_10q)
            if raw and (parsed := _as_date(raw)) is not None
        ]
        latest = (
            max(filing_dates, key=lambda item: (item[0], item[1]))[1]
            if filing_dates
            else None
        )
        provenance.append(
            (
                "sec",
                f"CIK {evidence.cik} companyfacts and EFTS",
                f"filed {latest}" if latest else "no filing date",
            )
        )
    return Dossier(
        symbol=symbol.strip().upper(),
        as_of=stamp,
        gates=tuple(gates),
        conflicts=tuple(filings.conflicts),
        red_flags=tuple(
            _hit_line(hit) for hit in evidence.hits if isinstance(hit, Mapping)
        ),
        provenance=tuple(provenance),
        coverage=coverage(gates),
    )
