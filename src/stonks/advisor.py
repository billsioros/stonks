"""Pure advisor helpers: candidate selection and local what-if math.

No Streamlit widgets and no provider calls live here. Candidates come from the
same screener query that feeds the table, and every portfolio number is derived
from supplied holdings so the AI never supplies one.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from stonks.report import AdvisorPick
from stonks.store import SQLiteStore

__all__ = [
    "WhatIfResult",
    "advisor_candidate_rows",
    "build_what_if",
    "universe_fingerprint",
]

_UNIVERSE_PAGE_SIZE = 100_000
_FULL_PERCENT = 100.0


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
