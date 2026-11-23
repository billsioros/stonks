"""Pure XBRL fact selection and cross-checks for Phase B filing evidence.

The caller supplies already-fetched SEC companyfacts JSON. Nothing here performs
I/O, imports Streamlit, or invents a figure: a check only passes when both the
filing fact and the vendor figure exist and agree within a fixed tolerance.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from stonks.dossier import Check

TOLERANCE_PCT = 0.01
TOLERANCE_ABS = 1_000_000.0
COVERAGE_MIN = 1.0
TOLERANCE_TEXT = "max(1% of XBRL value, $1,000,000)"

_FORM_RANK = {"10-K": 2, "10-Q": 1}
_NAMESPACES = ("us-gaap", "dei")

_REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
)
_NET_INCOME_TAGS = ("NetIncomeLoss",)
_OPERATING_CASH_FLOW_TAGS = ("NetCashProvidedByUsedInOperatingActivities",)
_CAPEX_TAGS = ("PaymentsToAcquirePropertyPlantAndEquipment",)
_SHARES_TAGS = ("dei:EntityCommonStockSharesOutstanding",)
_TOTAL_DEBT_TAGS = ("LongTermDebt", "DebtCurrent")
_CASH_TAGS = ("CashAndCashEquivalentsAtCarryingValue",)

_MATURITY_TAGS = (
    ("0-1y", "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths"),
    ("1-2y", "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo"),
    ("2-3y", "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree"),
    ("3-4y", "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour"),
    ("4-5y", "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive"),
    ("5y+", "LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive"),
)


@dataclass(frozen=True)
class _Fact:
    """A selected filing fact, with enough context to explain the selection."""

    value: float
    accn: str
    detail: str


@dataclass(frozen=True)
class _Vendor:
    """A vendor figure and the field it came from."""

    value: float
    source: str


@dataclass(frozen=True)
class _VendorSpec:
    row_keys: tuple[str, ...] = ()
    statements: tuple[tuple[str, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class _CheckSpec:
    id: str
    label: str
    tags: tuple[str, ...]
    unit: str
    vendor: _VendorSpec
    combine: bool = False


_CASH_VENDOR = _VendorSpec(
    row_keys=("cash",),
    statements=(
        (
            "balance_annual",
            (
                "cashneq",
                "cash",
                "cash & equivalents",
                "cash and cash equivalents",
                "cash and cash equivalents at carrying value",
            ),
        ),
    ),
)

_FCF_VENDOR = _VendorSpec(
    row_keys=("free_cash_flow",),
    statements=(
        ("cash_annual", ("fcf", "free cash flow")),
        ("income_annual", ("fcf", "free cash flow")),
    ),
)

_CHECKS = (
    _CheckSpec(
        "filings.revenue",
        "Revenue matches XBRL",
        _REVENUE_TAGS,
        "USD",
        _VendorSpec(
            ("revenue",),
            (
                (
                    "income_annual",
                    (
                        "revenue",
                        "revenues",
                        "total revenue",
                        "operating revenue",
                        "revenue as reported",
                    ),
                ),
            ),
        ),
    ),
    _CheckSpec(
        "filings.net_income",
        "Net income matches XBRL",
        _NET_INCOME_TAGS,
        "USD",
        _VendorSpec(
            ("net_income",),
            (
                (
                    "income_annual",
                    (
                        "netinc",
                        "net income",
                        "net income to common",
                        "net income to company",
                    ),
                ),
            ),
        ),
    ),
    _CheckSpec(
        "filings.operating_cash_flow",
        "Operating cash flow matches XBRL",
        _OPERATING_CASH_FLOW_TAGS,
        "USD",
        _VendorSpec(
            statements=(
                (
                    "cash_annual",
                    (
                        "cashfromoperations",
                        "cashfromops",
                        "netcashfromoperatingactivities",
                        "operating cash flow",
                        "cash from operations",
                        "net cash from operating activities",
                    ),
                ),
            ),
        ),
    ),
    _CheckSpec(
        "filings.capex",
        "Capital expenditure matches XBRL",
        _CAPEX_TAGS,
        "USD",
        _VendorSpec(
            statements=(
                (
                    "cash_annual",
                    (
                        "capex",
                        "capitalexpenditures",
                        "capital expenditures",
                        "payments to acquire property, plant & equipment",
                        "purchase of property, plant & equipment",
                    ),
                ),
            ),
        ),
    ),
    _CheckSpec(
        "filings.shares_out",
        "Shares outstanding match XBRL",
        _SHARES_TAGS,
        "shares",
        _VendorSpec(
            ("shares_out",),
            (
                (
                    "balance_annual",
                    (
                        "sharesouttotalcommon",
                        "sharesoutfilingdate",
                        "sharesout",
                        "shares outstanding",
                        "total common shares outstanding",
                    ),
                ),
            ),
        ),
    ),
    _CheckSpec(
        "filings.total_debt",
        "Total debt matches XBRL",
        _TOTAL_DEBT_TAGS,
        "USD",
        _VendorSpec(
            ("total_debt",),
            (("balance_annual", ("debt", "totaldebt", "total debt")),),
        ),
        combine=True,
    ),
    _CheckSpec("filings.cash", "Cash matches XBRL", _CASH_TAGS, "USD", _CASH_VENDOR),
)


def _number(value: object) -> float | None:
    """Accept only finite numbers (and numeric strings), never booleans."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip().replace(",", ""))
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return value
    return ()


def _fact_namespaces(facts: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept either the full companyfacts payload or its inner `facts` value."""
    inner = facts.get("facts")
    return inner if isinstance(inner, Mapping) else facts


def _latest_entry(facts: Mapping[str, Any], tag: str, unit: str) -> _Fact | None:
    """Pick the newest unamended 10-K/10-Q fact for one tag and unit."""
    prefix, separator, bare = tag.partition(":")
    if not separator:
        prefix, bare = "", prefix
    namespaces = _NAMESPACES if not prefix else (prefix,)

    for namespace in namespaces:
        payload = _fact_namespaces(facts).get(namespace)
        if not isinstance(payload, Mapping):
            continue
        tag_data = payload.get(bare)
        if not isinstance(tag_data, Mapping):
            continue
        units = tag_data.get("units")
        if not isinstance(units, Mapping):
            continue

        best_key: tuple[str, str, int, str] | None = None
        best_value: float | None = None
        best_detail = ""
        for entry in _sequence(units.get(unit)):
            if not isinstance(entry, Mapping):
                continue
            form = entry.get("form")
            if form not in _FORM_RANK:  # excludes 10-K/A and 10-Q/A
                continue
            end, filed = entry.get("end"), entry.get("filed")
            if not isinstance(end, str) or not isinstance(filed, str):
                continue
            value = _number(entry.get("val"))
            if value is None:
                continue
            raw_accn = entry.get("accn")
            accn = raw_accn if isinstance(raw_accn, str) else ""
            key = (end, filed, _FORM_RANK[form], accn)
            if best_key is None or key > best_key:
                best_key = key
                best_value = value
                best_detail = (
                    f"{namespace}:{bare} {form} filed {filed} accn {accn or 'unknown'}"
                )

        if best_value is not None:
            return _Fact(best_value, best_key[3] if best_key else "", best_detail)
    return None


def _first_fact(
    facts: Mapping[str, Any], tags: Sequence[str], unit: str
) -> _Fact | None:
    """Return the first usable fact across alias tags, with its filing context."""
    for tag in tags:
        fact = _latest_entry(facts, tag, unit)
        if fact is not None:
            return fact
    return None


def latest_fact(
    facts: Mapping[str, Any], tags: Sequence[str], unit: str
) -> tuple[float, str] | None:
    """Return ``(value, accession)`` from the first tag that has a usable fact."""
    fact = _first_fact(facts, tags, unit)
    return (fact.value, fact.accn) if fact is not None else None


def _combined_fact(facts: Mapping[str, Any], spec: _CheckSpec) -> _Fact | None:
    """Sum every required tag, refusing to report a partial total."""
    found = [_latest_entry(facts, tag, spec.unit) for tag in spec.tags]
    if any(fact is None for fact in found):
        return None
    facts_found = [fact for fact in found if fact is not None]
    accns = ", ".join(dict.fromkeys(fact.accn for fact in facts_found if fact.accn))
    return _Fact(
        sum(fact.value for fact in facts_found),
        accns,
        " + ".join(fact.detail for fact in facts_found),
    )


def _statement_value(
    statements: Mapping[str, Any], key: str, aliases: tuple[str, ...]
) -> _Vendor | None:
    """Read the latest non-TTM value of a statement row by id or label."""
    statement = statements.get(key)
    if not isinstance(statement, Mapping):
        return None
    wanted = {alias.casefold() for alias in aliases}
    periods = _sequence(statement.get("periods"))
    positions = [
        index
        for index, period in enumerate(periods)
        if isinstance(period, Mapping) and not period.get("is_ttm")
    ]

    for row in _sequence(statement.get("rows")):
        if not isinstance(row, Mapping):
            continue
        raw_id, raw_label = row.get("id"), row.get("label")
        identifier = raw_id if isinstance(raw_id, str) else ""
        label = raw_label if isinstance(raw_label, str) else ""
        if identifier.casefold() not in wanted and label.casefold() not in wanted:
            continue
        values = _sequence(row.get("values"))
        # A TTM-only statement cannot stand in for an annual or quarterly fact:
        # the vendor value it would be compared against uses a different period.
        # Statements without period metadata keep the legacy "scan all values"
        # behavior so older callers and fixtures remain readable.
        if periods and not positions:
            return None
        for index in positions or range(len(values)):
            if index < len(values):
                value = _number(values[index])
                if value is not None:
                    return _Vendor(value, f"{key}.{identifier or label}")
    return None


def _vendor_value(
    row: Mapping[str, Any], statements: Mapping[str, Any], spec: _VendorSpec
) -> _Vendor | None:
    """Prefer a screener key, then the matching statement id/label alias."""
    for key in spec.row_keys:
        value = _number(row.get(key))
        if value is not None:
            return _Vendor(value, f"screener.{key}")
    for key, aliases in spec.statements:
        found = _statement_value(statements, key, aliases)
        if found is not None:
            return found
    return None


def _money(value: float) -> str:
    return f"{value:,.0f}"


def _evidence(fact: _Fact | None, vendor: _Vendor | None, spec: _CheckSpec) -> str:
    separator = " + " if spec.combine else " / "
    filing = (
        fact.detail
        if fact
        else f"{separator.join(spec.tags)}: no qualifying 10-K/10-Q fact"
    )
    source = vendor.source if vendor else "no vendor figure"
    return f"{filing} vs {source}"


def _cross_check(
    spec: _CheckSpec,
    row: Mapping[str, Any],
    statements: Mapping[str, Any],
    facts: Mapping[str, Any],
) -> tuple[Check, str | None]:
    fact = (
        _combined_fact(facts, spec)
        if spec.combine
        else _first_fact(facts, spec.tags, spec.unit)
    )
    vendor = _vendor_value(row, statements, spec.vendor)

    if fact is None or vendor is None:
        reason = "no XBRL fact" if fact is None else "no vendor value"
        return (
            Check(
                spec.id,
                spec.label,
                "unverified",
                reason,
                TOLERANCE_TEXT,
                _evidence(fact, vendor, spec),
            ),
            None,
        )

    tolerance = max(TOLERANCE_PCT * abs(fact.value), TOLERANCE_ABS)
    gap = abs(fact.value - vendor.value)
    ok = gap <= tolerance
    status: Literal["pass", "fail"] = "pass" if ok else "fail"
    check = Check(
        spec.id,
        spec.label,
        status,
        f"filing {_money(fact.value)} vs vendor {_money(vendor.value)}",
        TOLERANCE_TEXT,
        _evidence(fact, vendor, spec),
    )
    conflict = (
        f"{spec.id}: XBRL {_money(fact.value)} ({fact.detail}) differs from "
        f"{vendor.source} {_money(vendor.value)}; gap {_money(gap)} > "
        f"tolerance {_money(tolerance)}"
        if not ok
        else None
    )
    return check, conflict


def maturity_ladder(facts: Mapping[str, Any]) -> list[tuple[str, float]] | None:
    """Return six dated debt buckets, or ``None`` if any required fact is absent."""
    ladder: list[tuple[str, float]] = []
    for label, tag in _MATURITY_TAGS:
        fact = _latest_entry(facts, tag, "USD")
        if fact is None:
            return None
        ladder.append((label, fact.value))
    return ladder


def _debt_coverage_check(
    row: Mapping[str, Any], statements: Mapping[str, Any], facts: Mapping[str, Any]
) -> Check:
    ladder = maturity_ladder(facts)
    cash_fact = _first_fact(facts, _CASH_TAGS, "USD")
    vendor_cash = _vendor_value(row, statements, _CASH_VENDOR)
    cash_value = (
        cash_fact.value if cash_fact else (vendor_cash.value if vendor_cash else None)
    )
    cash_source = (
        cash_fact.detail
        if cash_fact
        else (vendor_cash.source if vendor_cash else "no cash figure")
    )
    fcf = _vendor_value(row, statements, _FCF_VENDOR)
    sources = f"XBRL maturity ladder; {cash_source} + {fcf.source if fcf else 'no free-cash-flow figure'}"

    if ladder is None:
        return Check(
            "filings.debt_coverage",
            "Debt maturities are covered",
            "unverified",
            "no maturity ladder",
            f">= {COVERAGE_MIN:.1f}",
            sources,
        )
    due = ladder[0][1]
    if due <= 0 or cash_value is None or fcf is None:
        reason = (
            "no next-12-month maturity"
            if due <= 0
            else "no cash or free-cash-flow figure"
        )
        return Check(
            "filings.debt_coverage",
            "Debt maturities are covered",
            "unverified",
            reason,
            f">= {COVERAGE_MIN:.1f}",
            sources,
        )

    ratio = (cash_value + fcf.value) / due
    return Check(
        "filings.debt_coverage",
        "Debt maturities are covered",
        "pass" if ratio >= COVERAGE_MIN else "fail",
        f"({_money(cash_value)} cash + {_money(fcf.value)} FCF) / "
        f"{_money(due)} due in 12m = {ratio:.2f}",
        f">= {COVERAGE_MIN:.1f}",
        sources,
    )


def filing_checks(
    row: Mapping[str, Any], statements: Mapping[str, Any], facts: Mapping[str, Any]
) -> tuple[list[Check], list[str]]:
    """Cross-check the vendor's figures against XBRL and test debt coverage."""
    checks: list[Check] = []
    conflicts: list[str] = []
    for spec in _CHECKS:
        check, conflict = _cross_check(spec, row, statements, facts)
        checks.append(check)
        if conflict is not None:
            conflicts.append(conflict)
    checks.append(_debt_coverage_check(row, statements, facts))
    return checks, conflicts
