"""Portfolio backtesting over StockAnalysis's adjusted monthly closes.

The same history endpoint that feeds the detail chart also serves monthly bars
(``period=Monthly``) and an adjusted close in ``a`` where dividends are
reinvested, which is what a total-return backtest needs. Ten years is the
provider's cap, so that is the window offered here.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from stonks.detail_parse import parse_history
from stonks.stockanalysis import fetch_json
from stonks.store import SQLiteStore

HISTORY_URL = (
    "https://stockanalysis.com/api/symbol/s/{symbol}/history?range=10Y&period=Monthly"
)

# Map user-friendly tickers to StockAnalysis provider symbols.
# VUAA (Vanguard S&P 500 UCITS ETF) maps to VOO for API compatibility.
SYMBOL_MAP = {
    "VUAA": "VOO",
}

# Monthly bars change once a month; a few hours of cache is generous.
HISTORY_TTL_SECONDS = 6 * 3600.0

REBALANCE_MONTHS: dict[str, int] = {
    "none": 0,
    "annual": 12,
    "semiannual": 6,
    "quarterly": 3,
    "monthly": 1,
}
REBALANCE_LABELS: dict[str, str] = {
    "none": "No rebalancing",
    "annual": "Annually",
    "semiannual": "Semi-annually",
    "quarterly": "Quarterly",
    "monthly": "Monthly",
}

# Contribution cadences use the same month intervals as rebalancing.
CONTRIBUTION_MONTHS: dict[str, int] = dict(REBALANCE_MONTHS)


def monthly_url(symbol: str) -> str:
    """Build the monthly history URL for one symbol."""
    return HISTORY_URL.format(symbol=symbol.strip().lower())


def monthly_prices(
    store: SQLiteStore,
    symbol: str,
    *,
    fetch: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, float]:
    """Adjusted month-end closes for one symbol, keyed ``YYYY-MM``.

    Returns an empty mapping when the provider has no usable history.
    """
    key = f"hist:{symbol.strip().upper()}:10Y:Monthly"
    cached = store.cache_get(key)
    if isinstance(cached, dict) and cached:
        return dict(cached)  # type: ignore[arg-type]

    try:
        payload = (fetch or fetch_json)(monthly_url(symbol))
    except (OSError, ValueError):
        stale = store.cache_get(key, allow_expired=True)
        return dict(stale) if isinstance(stale, dict) else {}

    prices = {
        row["date"][:7]: row["close"] for row in parse_history(payload, adjusted=True)
    }
    if prices:
        store.cache_set(key, prices, ttl_seconds=HISTORY_TTL_SECONDS)
    return prices


def _monthly_returns(values: list[float]) -> list[float]:
    """Month-over-month simple returns."""
    return [
        values[i] / values[i - 1] - 1 for i in range(1, len(values)) if values[i - 1]
    ]


def _stdev(values: list[float]) -> float | None:
    """Sample standard deviation, or ``None`` with fewer than two values."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _max_drawdown(values: list[float]) -> float:
    """Deepest peak-to-trough decline as a negative percentage."""
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            worst = min(worst, value / peak - 1)
    return worst * 100


def _yearly_returns(curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Calendar-year returns from a monthly curve, each against the prior year."""
    closing: dict[str, float] = {}
    for point in curve:
        closing[str(point["date"])[:4]] = float(point["value"])
    rows: list[dict[str, Any]] = []
    previous = float(curve[0]["value"]) if curve else 0.0
    for year in sorted(closing):
        if previous:
            rows.append(
                {"year": year, "return_pct": (closing[year] / previous - 1) * 100}
            )
        previous = closing[year]
    return rows


def _annualized_irr(flows: list[tuple[int, float]]) -> float | None:
    """Annualize the monthly IRR of dated cash flows, or ``None`` if unsolvable."""

    def npv(rate: float) -> float:
        return sum(amount / (1 + rate) ** month for month, amount in flows)

    low, high = -0.9999, 1.0
    at_low = npv(low)
    while npv(high) * at_low > 0 and high < 1e6:
        high *= 2
    if npv(high) * at_low > 0:
        return None
    for _ in range(200):
        middle = (low + high) / 2
        if npv(middle) * at_low > 0:
            low = middle
        else:
            high = middle
    return ((1 + (low + high) / 2) ** 12 - 1) * 100


def simulate(
    prices: dict[str, dict[str, float]],
    weights: dict[str, float],
    *,
    rebalance: str = "annual",
    initial: float = 10_000.0,
    contributions: dict[str, float] | None = None,
    frequency: str = "none",
) -> dict[str, Any]:
    """Grow a portfolio with an initial amount and optional periodic deposits.

    Args:
        prices: ``{symbol: {"YYYY-MM": adjusted close}}``, one mapping per
            holding. Only months present in every series are used.
        weights: Target weight per symbol; normalised to sum to one.
        rebalance: One of :data:`REBALANCE_MONTHS`.
        initial: Starting portfolio value.
        contributions: Amount added per contribution, keyed by symbol.
        frequency: One of :data:`CONTRIBUTION_MONTHS`; ``none`` disables deposits.

    Returns:
        A result dict with the monthly ``curve`` and the summary statistics, or
        ``{"error": ...}`` when the inputs cannot produce a series. Performance
        statistics are time-weighted so deposits do not inflate them.
    """
    if not prices or not weights:
        return {"error": "Pick at least one symbol."}
    if rebalance not in REBALANCE_MONTHS:
        return {"error": f"Unknown rebalancing: {rebalance}"}
    if frequency not in CONTRIBUTION_MONTHS:
        return {"error": f"Unknown contribution frequency: {frequency}"}
    if initial < 0 or (
        contributions and any(amount < 0 for amount in contributions.values())
    ):
        return {"error": "Amounts cannot be negative."}
    if frequency == "none" and contributions:
        return {"error": "Choose a contribution frequency for recurring amounts."}

    months = sorted(set.intersection(*(set(series) for series in prices.values())))
    if len(months) < 2:
        return {"error": "Not enough overlapping price history for these symbols."}

    total_weight = sum(weights.values())
    if total_weight <= 0:
        return {"error": "Weights must add up to more than zero."}
    targets = {symbol: weight / total_weight for symbol, weight in weights.items()}
    step = CONTRIBUTION_MONTHS[frequency]
    additions = (
        {symbol: contributions.get(symbol, 0.0) for symbol in targets}
        if contributions
        else dict.fromkeys(targets, 0.0)
    )
    per_contribution = sum(additions.values())
    if initial + (per_contribution if step else 0) <= 0:
        return {"error": "Invest an initial amount or set recurring contributions."}

    invested = initial + (per_contribution if step else 0)
    units = {
        symbol: (initial * targets[symbol] + (additions[symbol] if step else 0))
        / prices[symbol][months[0]]
        for symbol in targets
    }
    every = REBALANCE_MONTHS[rebalance]
    curve: list[dict[str, Any]] = []
    growth = [1.0]
    flows = [(0, -invested)]

    first_value = sum(units[symbol] * prices[symbol][months[0]] for symbol in targets)
    curve.append({"date": months[0], "value": first_value})
    previous = first_value

    for index, month in enumerate(months[1:], start=1):
        value = sum(units[symbol] * prices[symbol][month] for symbol in targets)
        growth.append(growth[-1] * (value / previous if previous else 1.0))
        if step and index % step == 0:
            for symbol in targets:
                units[symbol] += additions[symbol] / prices[symbol][month]
            value += per_contribution
            invested += per_contribution
            flows.append((index, -per_contribution))
        if every and index % every == 0:
            # Rebalance at this month's close: the units change, the value does
            # not, and next month's returns then accrue on the target mix.
            units = {
                symbol: value * targets[symbol] / prices[symbol][month]
                for symbol in targets
            }
        previous = value
        curve.append({"date": month, "value": value})

    final = curve[-1]["value"]
    flows.append((len(months) - 1, final))
    index_curve = [
        {"date": month, "value": value} for month, value in zip(months, growth)
    ]
    years = (len(months) - 1) / 12
    total_return = growth[-1] - 1
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0
    deviation = _stdev(_monthly_returns(growth))
    yearly = _yearly_returns(index_curve)

    return {
        "start": months[0],
        "end": months[-1],
        "months": len(months),
        "initial": initial,
        "contribution": per_contribution if step else 0.0,
        "frequency": frequency,
        "invested": invested,
        "gain": final - invested,
        "final": final,
        "total_return_pct": total_return * 100,
        "cagr_pct": cagr * 100,
        "money_weighted_cagr_pct": _annualized_irr(flows)
        if step and per_contribution
        else None,
        "stdev_pct": deviation * math.sqrt(12) * 100 if deviation is not None else None,
        "max_drawdown_pct": _max_drawdown(growth),
        "best_year_pct": max((row["return_pct"] for row in yearly), default=None),
        "worst_year_pct": min((row["return_pct"] for row in yearly), default=None),
        "yearly": yearly,
        "curve": curve,
    }


def _benchmark_result(
    store: SQLiteStore,
    benchmark: str,
    result: dict[str, Any],
    initial: float,
    contributions: dict[str, float] | None,
    frequency: str,
) -> dict[str, Any]:
    """Grow the benchmark over the portfolio's months, for side-by-side stats."""
    from stonks.backtest import SYMBOL_MAP

    ticker = SYMBOL_MAP.get(benchmark.strip().upper(), benchmark.strip().upper())
    series = monthly_prices(store, ticker)
    if not series:
        return {"benchmark_error": f"No monthly price history for {ticker}."}
    keys = sorted(series)
    if len(keys) < 2:
        return {"benchmark_error": f"{ticker} has no history in the selected window."}
    # Filter to the portfolio's date window
    start_key = result["start"][:7]
    end_key = result["end"][:7]
    filtered = {k: series[k] for k in keys if start_key <= k <= end_key}
    if len(filtered) < 2:
        return {"benchmark_error": f"{ticker} has no history in the selected window."}
    stats = simulate(
        {ticker: filtered},
        {ticker: 1.0},
        rebalance="none",
        initial=initial,
        contributions={ticker: sum(contributions.values())} if contributions else None,
        frequency=frequency,
    )
    if "error" in stats:
        return {"benchmark_error": f"Could not grow {ticker}: {stats['error']}"}
    return {
        "benchmark": {
            "symbol": ticker,
            "start": stats["start"],
            "end": stats["end"],
            "final": stats["final"],
            "invested": stats["invested"],
            "gain": stats["gain"],
            "contribution": stats["contribution"],
            "frequency": stats["frequency"],
            "money_weighted_cagr_pct": stats["money_weighted_cagr_pct"],
            "total_return_pct": stats["total_return_pct"],
            "cagr_pct": stats["cagr_pct"],
            "stdev_pct": stats["stdev_pct"],
            "max_drawdown_pct": stats["max_drawdown_pct"],
            "yearly": stats["yearly"],
            "curve": stats["curve"],
        }
    }


def run_backtest(
    store: SQLiteStore,
    symbols: list[str],
    weights: list[float] | None = None,
    *,
    rebalance: str = "annual",
    start: str | None = None,
    end: str | None = None,
    initial: float = 10_000.0,
    benchmark: str | None = None,
    contributions: list[float] | None = None,
    frequency: str = "none",
    fetch: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Load each symbol's history and simulate the portfolio.

    Args:
        store: Cache owner for the monthly series.
        symbols: Tickers in the portfolio; case-insensitive, duplicates removed.
        weights: Optional weights in the same order as `symbols`; equal weight
            when omitted.
        rebalance: Rebalancing cadence, see :data:`REBALANCE_MONTHS`.
        start: Optional first month, inclusive, as ``YYYY-MM`` or ``YYYY-MM-DD``.
        end: Optional last month, inclusive, same format.
        initial: Starting portfolio value.
        contributions: Amount added per contribution, one per symbol.
        frequency: One of :data:`CONTRIBUTION_MONTHS`; ``none`` disables deposits.
        fetch: Optional JSON fetcher, for tests.

    Returns:
        See :func:`simulate`; a missing symbol is reported in ``error``.
    """
    unique: list[str] = []
    for symbol in symbols:
        ticker = symbol.strip().upper()
        if ticker and ticker not in unique:
            unique.append(ticker)
    if not unique:
        return {"error": "Pick at least one symbol."}
    if weights is not None and len(weights) != len(unique):
        return {"error": "Give one weight per symbol, or none for equal weight."}
    if contributions is not None and len(contributions) != len(unique):
        return {"error": "Give one contribution per symbol, or none."}

    prices: dict[str, dict[str, float]] = {}
    missing: list[str] = []
    for ticker in unique:
        series = monthly_prices(store, ticker, fetch=fetch)
        if not series:
            missing.append(ticker)
            continue
        prices[ticker] = series
    if missing:
        return {"error": f"No monthly price history for {', '.join(missing)}."}

    start_key = (start or "")[:7]
    end_key = (end or "")[:7]
    for ticker, series in prices.items():
        prices[ticker] = {
            month: value
            for month, value in series.items()
            if (not start_key or month >= start_key)
            and (not end_key or month <= end_key)
        }

    chosen = (
        dict(zip(unique, weights, strict=True))
        if weights is not None
        else dict.fromkeys(unique, 1.0)
    )
    contribution_map = (
        dict(zip(unique, contributions, strict=True)) if contributions else None
    )
    result = simulate(
        prices,
        chosen,
        rebalance=rebalance,
        initial=initial,
        contributions=contribution_map,
        frequency=frequency,
    )
    result["symbols"] = unique
    result["contributions"] = contribution_map
    result["weights"] = {
        ticker: weight / sum(chosen.values()) * 100 for ticker, weight in chosen.items()
    }
    result["rebalance"] = rebalance
    if benchmark:
        result.update(
            _benchmark_result(
                store, benchmark, result, initial, contribution_map, frequency
            )
        )
    return result
