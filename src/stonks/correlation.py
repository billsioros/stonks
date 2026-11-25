"""Correlation of portfolio monthly returns with a candidate and with itself.

Screener candidates and the portfolio card share one price-behaviour measure:
Pearson correlation of monthly adjusted returns over the last 36 months, using
native-currency returns and the backtest's VUAA→VOO provider mapping. A value
at or above 0.70 counts as highly correlated. Months with no overlap in either
series, or fewer than 12 overlapping months, produce no number rather than a
fabricated one.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections.abc import Callable
from itertools import pairwise
from typing import Any

from stonks.backtest import HISTORY_TTL_SECONDS, monthly_prices, provider_symbol
from stonks.portfolio import PortfolioSummary, backtest_allocation
from stonks.store import SQLiteStore

# Three years of monthly bars: long enough for a stable pairwise statistic and
# short enough that the relationship is still current.
LOOKBACK_MONTHS = 36
# Two years of overlap is too noisy; one year is the shortest useful window.
MIN_OVERLAP_MONTHS = 12
# Pinned "high correlation" cutoff for the screener flag and card tooltip.
HIGH_CORRELATION_THRESHOLD = 0.70


def _fingerprint(rows: list[list[Any]]) -> str:
    """Stable short hash of a sortable list of rows."""
    payload = json.dumps(sorted(rows), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def position_fingerprint(positions: list[dict[str, Any]]) -> str:
    """Short hash identifying one set of lots, so edits invalidate the cache."""
    return _fingerprint(
        [
            [lot["symbol"], lot["quantity"], lot["price"], lot["currency"]]
            for lot in positions
        ]
    )


def allocation_fingerprint(symbols: list[str], weights: list[float]) -> str:
    """Short hash identifying one weighted allocation."""
    return _fingerprint(
        [[symbol, round(weight, 6)] for symbol, weight in zip(symbols, weights)]
    )


def is_high_correlation(value: float | None) -> bool:
    """Whether a correlation meets the screener's high-correlation threshold."""
    return value is not None and value >= HIGH_CORRELATION_THRESHOLD


def _cached_float(store: SQLiteStore, key: str) -> float | None:
    """Return a usable cached correlation, ignoring malformed entries."""
    cached = store.cache_get(key)
    if isinstance(cached, bool) or not isinstance(cached, (int, float)):
        return None
    value = float(cached)
    return value if math.isfinite(value) else None


def _monthly_returns(prices: dict[str, float]) -> dict[str, float]:
    """Month-keyed simple returns over the lookback window."""
    months = sorted(prices)[-(LOOKBACK_MONTHS + 1) :]
    returns: dict[str, float] = {}
    for previous, current in pairwise(months):
        base = prices[previous]
        if base:
            returns[current] = prices[current] / base - 1
    return returns


def _weighted_returns(
    returns: dict[str, dict[str, float]], weights: dict[str, float]
) -> dict[str, float]:
    """Portfolio return per month where every holding has a return."""
    if not returns:
        return {}
    months = set.intersection(*(set(series) for series in returns.values()))
    return {
        month: sum(
            weights[symbol] / 100 * series[month] for symbol, series in returns.items()
        )
        for month in months
    }


def _pearson(left: list[float], right: list[float]) -> float | None:
    """Pearson correlation, or ``None`` when it cannot be computed."""
    try:
        value = statistics.correlation(left, right)
    except statistics.StatisticsError:
        return None
    return value if math.isfinite(value) else None


def portfolio_correlation(
    store: SQLiteStore,
    symbol: str,
    summary: PortfolioSummary,
    positions: list[dict[str, Any]],
    *,
    fetch: Callable[[str], dict[str, Any]] | None = None,
) -> float | None:
    """Correlation of one candidate with the weighted holdings' returns."""
    key = f"corr:v1:{provider_symbol(symbol)}:{position_fingerprint(positions)}"
    cached = _cached_float(store, key)
    if cached is not None:
        return cached

    symbols, weights = backtest_allocation(summary)
    if not symbols:
        return None

    held = {
        held_symbol: _monthly_returns(monthly_prices(store, held_symbol, fetch=fetch))
        for held_symbol in symbols
    }
    candidate = _monthly_returns(monthly_prices(store, symbol, fetch=fetch))
    combined = _weighted_returns(held, dict(zip(symbols, weights)))
    months = sorted(set(combined) & set(candidate))
    if len(months) < MIN_OVERLAP_MONTHS:
        return None

    value = _pearson(
        [combined[month] for month in months],
        [candidate[month] for month in months],
    )
    if value is None:
        return None
    store.cache_set(key, value, ttl_seconds=HISTORY_TTL_SECONDS)
    return value


def portfolio_correlation_factor(
    store: SQLiteStore,
    symbols: list[str],
    weights: list[float],
    *,
    fetch: Callable[[str], dict[str, Any]] | None = None,
) -> float | None:
    """Weight-normalised average pairwise correlation of an allocation."""
    positive = [
        (symbol, float(weight))
        for symbol, weight in zip(symbols, weights)
        if weight > 0
    ]
    if len(positive) < 2:
        return None

    key = f"corr:factor:v1:{allocation_fingerprint(symbols, weights)}"
    cached = _cached_float(store, key)
    if cached is not None:
        return cached

    total = sum(weight for _, weight in positive)
    series = [
        (
            weight / total,
            _monthly_returns(monthly_prices(store, symbol, fetch=fetch)),
        )
        for symbol, weight in positive
    ]

    weighted_sum = 0.0
    weight_sum = 0.0
    for index, (weight_i, returns_i) in enumerate(series):
        for weight_j, returns_j in series[index + 1 :]:
            months = sorted(set(returns_i) & set(returns_j))
            if len(months) < MIN_OVERLAP_MONTHS:
                return None
            value = _pearson(
                [returns_i[month] for month in months],
                [returns_j[month] for month in months],
            )
            if value is None:
                return None
            weighted_sum += value * weight_i * weight_j
            weight_sum += weight_i * weight_j

    if weight_sum <= 0:
        return None
    factor = weighted_sum / weight_sum
    if not math.isfinite(factor):
        return None
    store.cache_set(key, factor, ttl_seconds=HISTORY_TTL_SECONDS)
    return factor
