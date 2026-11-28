"""Advisor tab: candidate selection, local what-if math, generation flow.

Candidates come from the same screener query that feeds the table, and every
portfolio number is derived from supplied holdings so the AI never supplies
one. `render_advisor_tab` owns the Streamlit controls and the single Generate
button; the provider call itself stays in `report_view`, and no portfolio or
store writes ever happen here.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import streamlit as st

from stonks import report, report_view
from stonks.backtest_view import queue_backtest_settings
from stonks.correlation import (
    HIGH_CORRELATION_THRESHOLD,
    is_high_correlation,
    portfolio_correlation,
    portfolio_correlation_factor,
)
from stonks.portfolio import PortfolioSummary, backtest_allocation, portfolio_snapshot
from stonks.report import AdvisorPick
from stonks.store import SQLiteStore

__all__ = [
    "WhatIfResult",
    "advisor_candidate_rows",
    "build_what_if",
    "render_advisor_tab",
    "universe_fingerprint",
]

_UNIVERSE_PAGE_SIZE = 100_000
_FULL_PERCENT = 100.0

_ADVISOR_SCOPE_KEY = "advisor-llm-report"
_ADVISOR_HEADING = "🤖 AI report"
_ADVISOR_PICK_COUNT_KEY = "advisor_pick_count"
_ADVISOR_GENERATE_KEY = "advisor_generate"
_DEFAULT_PICK_COUNT = 5
_MIN_PICK_COUNT = 1
_MAX_PICK_COUNT = 10
_NO_MATCHES_MESSAGE = "⚠️ No stocks match your current filters"
_NO_NEW_MATCHES_MESSAGE = "⚠️ No new stocks match your current filters"
_STALE_MESSAGE = (
    "⚠️ Advisor results are stale: filters, search, or pick count changed. "
    "Press ✨ Generate recommendations to refresh."
)
_ADVISOR_COLUMNS: tuple[str, ...] = (
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
)
_ADVISOR_TABLE_KEY = "advisor_picks_table"
_ADVISOR_BACKTEST_KEY = "advisor_send_backtest"
_MISSING = "—"
_CAP_WARNING = "Suggested weights totalled over 100%, so they were scaled to 99%."


@dataclass(frozen=True)
class WhatIfResult:
    """Before/after allocation for the checked advisor picks.

    `current_weights` are normalized to 100; `after_weights` hold the diluted
    existing weights followed by the checked picks' capped target weights and
    also sum to 100. `added_cash` is the cash implied by those target weights,
    not an amount the user entered.
    """

    current_symbols: tuple[str, ...]
    current_weights: tuple[float, ...]
    after_symbols: tuple[str, ...]
    after_weights: tuple[float, ...]
    current_total: float
    added_cash: float
    after_total: float
    total_target_pct: float
    cap_applied: bool


def build_what_if(
    holdings: Sequence[tuple[str, float]],
    picks: Sequence[AdvisorPick],
    checked: Sequence[bool],
    *,
    cap_pct: float = 99.0,
) -> WhatIfResult:
    """Dilute priced holdings by the checked target weights of advisor picks.

    The cap is applied to every pick before checkboxes are read, so unchecking
    one pick can only leave more weight in the existing portfolio; it never
    re-inflates the other picks. Existing weights are normalized to 100, then
    multiplied by ``1 - T`` where ``T`` is the checked target total as a
    fraction. The implied cash is ``current_total * T / (1 - T)``. With no
    priced holdings there is no rail, so every after field is empty.
    """
    priced = [
        (str(symbol), float(value))
        for symbol, value in holdings
        if math.isfinite(value) and value > 0
    ]
    current_total = math.fsum(value for _, value in priced)
    if current_total <= 0:
        return WhatIfResult(
            current_symbols=(),
            current_weights=(),
            after_symbols=(),
            after_weights=(),
            current_total=0.0,
            added_cash=0.0,
            after_total=0.0,
            total_target_pct=0.0,
            cap_applied=False,
        )

    current_symbols = tuple(symbol for symbol, _ in priced)
    current_weights = tuple(
        value / current_total * _FULL_PERCENT for _, value in priced
    )

    raw_total = math.fsum(pick.weight for pick in picks)
    cap_applied = raw_total > cap_pct
    scale = cap_pct / raw_total if cap_applied and raw_total > 0 else 1.0
    capped = [pick.weight * scale for pick in picks]

    selected = [weight for weight, on in zip(capped, checked) if on]
    selected_symbols = tuple(str(pick.symbol) for pick, on in zip(picks, checked) if on)
    total_target_pct = math.fsum(selected)

    fraction = total_target_pct / _FULL_PERCENT
    added_cash = current_total * fraction / (1.0 - fraction)
    dilution = 1.0 - fraction
    return WhatIfResult(
        current_symbols=current_symbols,
        current_weights=current_weights,
        after_symbols=current_symbols + selected_symbols,
        after_weights=tuple(weight * dilution for weight in current_weights)
        + tuple(selected),
        current_total=current_total,
        added_cash=added_cash,
        after_total=current_total + added_cash,
        total_target_pct=total_target_pct,
        cap_applied=cap_applied,
    )


def universe_fingerprint(active_filters: Mapping[str, Any], search_query: str) -> str:
    """Stable digest of the screener universe behind a generated advisor result."""
    payload = json.dumps(
        {"filters": active_filters, "search": search_query},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def advisor_candidate_rows(
    store: SQLiteStore,
    *,
    active_filters: Mapping[str, Any] | None,
    search_query: str,
    sort_column: str | None,
    sort_ascending: bool,
    held_symbols: Collection[str],
) -> list[dict[str, Any]]:
    """Screener rows matching the current query, minus already-held symbols.

    One query fetches the whole filtered universe so the candidate pool cannot
    drift from the screener table; already-held tickers are then dropped so an
    advisor pick always means a new position.
    """
    rows, _, _ = store.get_stocks(
        filters=dict(active_filters) if active_filters is not None else None,
        search_query=search_query,
        sort_column=sort_column,
        sort_ascending=sort_ascending,
        page=1,
        page_size=_UNIVERSE_PAGE_SIZE,
    )
    held = {str(symbol).upper() for symbol in held_symbols}
    return [row for row in rows if str(row.get("symbol") or "").upper() not in held]


def _finite(value: Any) -> float | None:
    """A finite number, or None for a missing/blank/non-numeric cell."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str:
    """Plain cell text, with a dash for missing values."""
    if value is None:
        return _MISSING
    text = str(value).strip()
    return text or _MISSING


def _number_text(value: Any) -> str:
    """A two-decimal figure, or a dash when the cell has no number."""
    number = _finite(value)
    return _MISSING if number is None else f"{number:.2f}"


def _percent_text(value: Any) -> str:
    """A one-decimal percentage, or a dash when the cell has no number."""
    number = _finite(value)
    return _MISSING if number is None else f"{number:.1f}%"


def _correlation_text(value: float | None) -> str:
    """Screener-style correlation: ⚠️ at the high threshold, dash if missing."""
    number = _finite(value)
    if number is None:
        return _MISSING
    prefix = "⚠️ " if is_high_correlation(number) else ""
    return f"{prefix}{number:+.2f}"


def _factor_text(value: float | None) -> str:
    """Portfolio correlation factor, or a dash when it cannot be computed."""
    number = _finite(value)
    return _MISSING if number is None else f"{number:+.2f}"


def _advisor_table_rows(
    store: SQLiteStore,
    picks: Sequence[AdvisorPick],
    row_by_symbol: Mapping[str, Mapping[str, Any]],
    summary: PortfolioSummary,
    positions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """One ranked, display-only row per pick, with locally computed numbers."""
    rows: list[dict[str, Any]] = []
    for rank, pick in enumerate(picks, start=1):
        row = row_by_symbol.get(str(pick.symbol).strip().upper(), {})
        correlation = portfolio_correlation(store, pick.symbol, summary, positions)
        rows.append(
            {
                "Select": True,
                "Rank": rank,
                "Symbol": pick.symbol,
                "Description": _text(row.get("description")),
                "Industry": _text(row.get("industry")),
                "Weight %": _percent_text(pick.weight),
                "Why": _text(pick.reason),
                "Portfolio correlation": _correlation_text(correlation),
                "Price": _number_text(row.get("price")),
                "P/E": _number_text(row.get("pe_ratio")),
                "PT upside %": _percent_text(row.get("pt_upside_pct")),
                "DCF upside %": _percent_text(row.get("dcf_upside_pct")),
            }
        )
    return rows


def _industry_of(row: Mapping[str, Any]) -> str:
    """Industry bucket for one screener row, with an explicit Unknown bucket."""
    value = row.get("industry")
    text = str(value).strip() if value is not None else ""
    return text or "Unknown"


def _industry_weights(
    symbols: Sequence[str],
    weights: Sequence[float],
    industry_by_symbol: Mapping[str, str],
) -> dict[str, float]:
    """Aggregate allocation weights into industry buckets."""
    totals: dict[str, float] = {}
    for symbol, weight in zip(symbols, weights):
        industry = industry_by_symbol.get(str(symbol).strip().upper(), "Unknown")
        totals[industry] = totals.get(industry, 0.0) + float(weight)
    return totals


def _render_what_if_rail(
    store: SQLiteStore,
    what_if: WhatIfResult,
    row_by_symbol: Mapping[str, Mapping[str, Any]],
    *,
    stale: bool,
    any_checked: bool,
) -> None:
    """Show the before/after allocation and hand it to the backtest tab."""
    st.caption("What-if allocation")
    before_factor: float | None = None
    after_factor: float | None = None
    if what_if.current_total <= 0:
        st.warning("Add a priced portfolio to use what-if")
    else:
        st.markdown(
            f"**Portfolio total** · before ${what_if.current_total:,.2f} → "
            f"after ${what_if.after_total:,.2f} "
            f"(+${what_if.added_cash:,.2f} implied cash)"
        )
        top = sorted(
            zip(what_if.after_symbols, what_if.after_weights),
            key=lambda pair: pair[1],
            reverse=True,
        )[:3]
        if top:
            holdings = ", ".join(f"{symbol} {weight:.1f}%" for symbol, weight in top)
            st.markdown(f"**Top holdings** · {holdings}")
            st.markdown(f"**Largest weight** · {top[0][0]} {top[0][1]:.1f}%")

        before_factor = portfolio_correlation_factor(
            store, list(what_if.current_symbols), list(what_if.current_weights)
        )
        after_factor = portfolio_correlation_factor(
            store, list(what_if.after_symbols), list(what_if.after_weights)
        )
        st.markdown(
            f"**Portfolio correlation** · before {_factor_text(before_factor)} → "
            f"after {_factor_text(after_factor)}"
        )

        industry_by_symbol = {
            symbol: _industry_of(row) for symbol, row in row_by_symbol.items()
        }
        before = _industry_weights(
            what_if.current_symbols, what_if.current_weights, industry_by_symbol
        )
        after = _industry_weights(
            what_if.after_symbols, what_if.after_weights, industry_by_symbol
        )
        lines = ["| Industry | Before | After |", "| --- | ---: | ---: |"]
        for industry in sorted(set(before) | set(after)):
            label = industry.replace("|", "\\|")
            lines.append(
                f"| {label} | {before.get(industry, 0.0):.1f}% | "
                f"{after.get(industry, 0.0):.1f}% |"
            )
        st.markdown("**Industry weights**")
        st.markdown("\n".join(lines))

    if what_if.cap_applied:
        st.warning(_CAP_WARNING)

    can_handoff = not stale and any_checked and what_if.current_total > 0
    if st.button(
        "🧪 Send to backtest", key=_ADVISOR_BACKTEST_KEY, disabled=not can_handoff
    ):
        queue_backtest_settings(
            {
                "symbols": list(what_if.after_symbols),
                "weights": list(what_if.after_weights),
                "initial": what_if.after_total,
                "contribution": 0.0,
            }
        )
        st.session_state["page"] = "backtest"
        st.rerun()


def render_advisor_tab(store: SQLiteStore) -> None:
    """Render the Advisor tab: controls, one Generate button, AI drawer.

    Candidates are the current screener results (active filters + search,
    whole universe) minus already-held symbols. Freshness compares the stored
    `pick_count` and `universe_fingerprint(active_filters, search_query)`;
    sort order alone never invalidates. On a provider or parse failure the
    stored result has `report=None`, keeps `raw`/`prompt` when available, and
    `report.explain_error(exc)` is passed to the drawer. A stored report also
    drives the ranked, selectable table and the local what-if rail; neither
    writes to the store.
    """
    active_filters = st.session_state.get("active_filters") or {}
    search_query = st.session_state.get("search_query") or ""
    sort_column = st.session_state.get("sort_column")
    sort_ascending = st.session_state.get("sort_ascending", True)

    positions = store.get_positions()
    held_symbols = {str(lot.get("symbol") or "").strip().upper() for lot in positions}
    held_symbols.discard("")

    fingerprint = universe_fingerprint(active_filters, search_query)

    # Read the current count before rendering the widget; Streamlit has already
    # applied any pending widget change to session state on this rerun.
    pick_count = _current_pick_count()

    state = st.session_state.get(_ADVISOR_SCOPE_KEY)
    stale = _is_stale(state, pick_count=pick_count, fingerprint=fingerprint)
    if stale:
        st.warning(_STALE_MESSAGE)

    matching = advisor_candidate_rows(
        store,
        active_filters=active_filters,
        search_query=search_query,
        sort_column=sort_column,
        sort_ascending=sort_ascending,
        held_symbols=frozenset(),
    )
    if not matching:
        st.warning(_NO_MATCHES_MESSAGE)
        return

    candidates = advisor_candidate_rows(
        store,
        active_filters=active_filters,
        search_query=search_query,
        sort_column=sort_column,
        sort_ascending=sort_ascending,
        held_symbols=held_symbols,
    )
    if not candidates:
        st.warning(_NO_NEW_MATCHES_MESSAGE)
        return

    pick_count = int(
        st.number_input(
            "How many picks?",
            key=_ADVISOR_PICK_COUNT_KEY,
            min_value=_MIN_PICK_COUNT,
            max_value=_MAX_PICK_COUNT,
            value=_DEFAULT_PICK_COUNT,
        )
    )
    clicked = st.button("✨ Generate recommendations", key=_ADVISOR_GENERATE_KEY)

    error: str | None = None
    if clicked:
        error = _generate_advisor_report(
            store,
            candidates=candidates,
            pick_count=pick_count,
            positions=positions,
            fingerprint=fingerprint,
        )
        state = st.session_state.get(_ADVISOR_SCOPE_KEY)
        stale = _is_stale(state, pick_count=pick_count, fingerprint=fingerprint)

    parsed = state.get("report") if isinstance(state, Mapping) else None
    summary, _stale_fx = portfolio_snapshot(store, include_history=False)
    holdings = [
        (holding.symbol, holding.market_usd)
        for holding in summary.holdings
        if holding.market_usd is not None
        and math.isfinite(holding.market_usd)
        and holding.market_usd > 0
    ]
    picks = tuple(parsed.picks)[:pick_count] if parsed is not None else ()

    # The cap is decided before any checkbox is read, so the drawer can show the
    # same warning as the rail even though the table is rendered afterwards.
    cap_probe = build_what_if(holdings, picks, [True] * len(picks))
    report_view.render_advisor_report(
        scope_key=_ADVISOR_SCOPE_KEY,
        heading=_ADVISOR_HEADING,
        generate_clicked=clicked,
        generate_error=error,
        cap_warning=cap_probe.cap_applied,
    )
    if not picks:
        return

    row_by_symbol = {
        str(row.get("symbol") or "").strip().upper(): row for row in matching
    }
    table_col, rail_col = st.columns([3, 2], vertical_alignment="top")
    with table_col:
        if positions:
            st.caption(
                f"⚠️ marks correlation at or above "
                f"{HIGH_CORRELATION_THRESHOLD:.2f} with the portfolio."
            )
        disabled = [column for column in _ADVISOR_COLUMNS if column != "Select"]
        if stale:
            disabled.append("Select")
        edited = st.data_editor(
            pd.DataFrame(
                _advisor_table_rows(store, picks, row_by_symbol, summary, positions),
                columns=list(_ADVISOR_COLUMNS),
            ),
            column_config={
                "Select": st.column_config.CheckboxColumn("Select", default=True)
            },
            disabled=disabled,
            hide_index=True,
            width="stretch",
            key=_ADVISOR_TABLE_KEY,
        )
        checked = [bool(value) for value in edited["Select"]]

    what_if = build_what_if(holdings, picks, checked)
    with rail_col:
        _render_what_if_rail(
            store,
            what_if,
            row_by_symbol,
            stale=stale,
            any_checked=any(checked),
        )


def _current_pick_count() -> int:
    """The pick count currently selected, clamped to the widget's range."""
    raw = st.session_state.get(_ADVISOR_PICK_COUNT_KEY, _DEFAULT_PICK_COUNT)
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_PICK_COUNT
    return max(_MIN_PICK_COUNT, min(_MAX_PICK_COUNT, count))


def _is_stale(state: Any, *, pick_count: int, fingerprint: str) -> bool:
    """A stored result is stale when count or universe fingerprint changed."""
    if not isinstance(state, Mapping):
        return False
    return (
        state.get("pick_count") != pick_count or state.get("fingerprint") != fingerprint
    )


def _generate_advisor_report(
    store: SQLiteStore,
    *,
    candidates: Sequence[Mapping[str, Any]],
    pick_count: int,
    positions: list[dict[str, Any]],
    fingerprint: str,
) -> str | None:
    """Run one Generate click: build prompt, request, parse, store six keys.

    Returns the drawer error string (`report.explain_error(exc)`) on provider
    or parse failure; the raw reply and prompt are kept when available.
    """
    scope_key = _ADVISOR_SCOPE_KEY
    prompt = ""
    raw = ""
    try:
        prompt = _build_advisor_prompt(
            store, candidates=candidates, pick_count=pick_count, positions=positions
        )
        raw = report_view.request_advisor_report(
            prompt,
            api_key=os.environ.get("OPENROUTER_API_KEY") or "",
            model=os.environ.get("OPENROUTER_MODEL") or report.REPORT_MODEL,
        )
        allowed_symbols = {
            str(row.get("symbol") or "").strip().upper()
            for row in candidates
            if str(row.get("symbol") or "").strip()
        }
        parsed = report.parse_advisor_reply(raw, allowed_symbols)
        shortfall = max(0, pick_count - len(parsed.picks))
        st.session_state[scope_key] = {
            "report": parsed,
            "raw": raw,
            "prompt": prompt,
            "pick_count": pick_count,
            "fingerprint": fingerprint,
            "shortfall": shortfall,
        }
    except Exception as exc:  # noqa: BLE001 - never crash the tab on provider/parse failure
        st.session_state[scope_key] = {
            "report": None,
            "raw": raw,
            "prompt": prompt,
            "pick_count": pick_count,
            "fingerprint": fingerprint,
            "shortfall": pick_count,
        }
        return report.explain_error(exc)
    return None


def _build_advisor_prompt(
    store: SQLiteStore,
    *,
    candidates: Sequence[Mapping[str, Any]],
    pick_count: int,
    positions: list[dict[str, Any]],
) -> str:
    """Holdings context from `portfolio_snapshot` + `portfolio_correlation`.

    The prompt carries only supplied screener rows and holdings; every number
    comes from local functions, never from the AI.
    """
    summary, _stale = portfolio_snapshot(store, include_history=False)
    symbols, weights = backtest_allocation(summary)
    weight_by_symbol = dict(zip(symbols, weights))
    industry_by_symbol = _screener_industry(store, symbols)

    holdings: list[dict[str, Any]] = []
    for holding in summary.holdings:
        holdings.append(
            {
                "symbol": holding.symbol,
                "weight_pct": weight_by_symbol.get(holding.symbol),
                "industry": industry_by_symbol.get(holding.symbol.strip().upper()),
                "correlation": portfolio_correlation(
                    store, holding.symbol, summary, positions
                ),
            }
        )

    correlation_factor = portfolio_correlation_factor(store, symbols, weights)
    return report.advisor_report_prompt(
        [dict(row) for row in candidates],
        pick_count,
        holdings,
        correlation_factor,
    )


def _screener_industry(store: SQLiteStore, symbols: Sequence[str]) -> dict[str, Any]:
    """Screener industry per symbol (uppercased key); missing stays missing."""
    if not symbols:
        return {}
    rows, _, _ = store.get_stocks(
        filters={"symbol": {"values": list(symbols)}},
        page=1,
        page_size=len(symbols),
    )
    return {
        str(row.get("symbol") or "").strip().upper(): row.get("industry")
        for row in rows
    }
