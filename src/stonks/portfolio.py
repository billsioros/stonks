"""Manual portfolio lots: validation, cached FX and USD valuation."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from stonks import detail
from stonks.stockanalysis import fetch_json
from stonks.store import SQLiteStore

FX_URL = "https://api.frankfurter.app/latest?from=EUR&to=USD"
FX_CACHE_KEY = "fx:EURUSD"
FX_TTL_SECONDS = 24 * 3600.0
CONVERTIBLE_CURRENCIES = frozenset({"USD", "EUR"})


@dataclass(frozen=True)
class Holding:
    """One symbol's aggregated lots, valued in its instrument currency and USD."""

    symbol: str
    description: str
    currency: str
    quantity: float
    last: float | None
    change_pct: float | None
    cost_native: float | None
    cost_usd: float | None
    market_native: float | None
    market_usd: float | None
    avg_price: float | None
    daily_pnl_native: float | None
    daily_pnl_usd: float | None
    unrealized_native: float | None
    unrealized_usd: float | None


@dataclass(frozen=True)
class PortfolioSummary:
    """Holdings and headline totals; any unusable holding is excluded."""

    holdings: tuple[Holding, ...]
    total_cost_usd: float | None
    total_value_usd: float | None
    daily_pnl_usd: float | None
    unrealized_pnl_usd: float | None
    unrealized_pct: float | None
    excluded_symbols: tuple[str, ...]
    usd_per_eur: float | None


def _positive_number(value: Any) -> float | None:
    """Accept only a finite, strictly positive number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _rate(rates: dict[str, float | None], currency: str) -> float | None:
    """Look up an exchange rate, rejecting unsupported currencies."""
    code = currency.strip().upper()
    if code not in CONVERTIBLE_CURRENCIES:
        return None
    return _positive_number(rates.get(code))


def validate_lot(symbol: str, quantity: float, price: float, currency: str) -> None:
    """Check the manual-lot contract before writing it to the store."""
    if not symbol or not symbol.strip():
        raise ValueError("Symbol is required")
    if _positive_number(quantity) is None:
        raise ValueError("Quantity must be a positive finite number")
    if _positive_number(price) is None:
        raise ValueError("Price must be a positive finite number")
    if currency.strip().upper() not in CONVERTIBLE_CURRENCIES:
        raise ValueError("Currency must be USD or EUR")


def parse_fx_rate(payload: dict[str, Any]) -> float | None:
    """Extract the EUR→USD rate from a Frankfurter ``latest`` payload."""
    try:
        return _positive_number(payload["rates"]["USD"])
    except (KeyError, TypeError):
        return None


def usd_rate(
    store: SQLiteStore,
    currency: str,
    *,
    fetch: Callable[[str], dict[str, Any]] | None = None,
) -> tuple[float | None, bool]:
    """Return ``(rate_to_usd, served_from_stale_cache)`` for one currency."""
    code = currency.strip().upper()
    if code == "USD":
        return 1.0, False
    if code not in CONVERTIBLE_CURRENCIES:
        raise ValueError("Currency must be USD or EUR")

    fresh = _positive_number(store.cache_get(FX_CACHE_KEY))
    if fresh is not None:
        return fresh, False

    try:
        payload = (fetch or fetch_json)(FX_URL)
    except (OSError, ValueError, TypeError):
        payload = None
    fetched = parse_fx_rate(payload) if payload is not None else None
    if fetched is not None:
        store.cache_set(FX_CACHE_KEY, fetched, ttl_seconds=FX_TTL_SECONDS)
        return fetched, False

    stale = _positive_number(store.cache_get(FX_CACHE_KEY, allow_expired=True))
    if stale is not None:
        return stale, True
    return None, False


def _lot_costs(
    lots: list[dict[str, Any]], currency: str, rates: dict[str, float | None]
) -> tuple[float | None, float | None]:
    """Total cost in display currency and in USD; ``None`` if a rate is missing."""
    display_rate = _rate(rates, currency)
    if display_rate is None:
        return None, None
    cost_native = 0.0
    cost_usd = 0.0
    for lot in lots:
        lot_currency = str(lot["currency"]).strip().upper()
        lot_rate = _rate(rates, lot_currency)
        if lot_rate is None:
            return None, None
        basis = float(lot["quantity"]) * float(lot["price"])
        cost_usd += basis * lot_rate
        cost_native += (
            basis if lot_currency == currency else basis * lot_rate / display_rate
        )
    return cost_native, cost_usd


def build_portfolio_summary(
    positions: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
    prior_closes: dict[str, float],
    rates: dict[str, float | None],
) -> PortfolioSummary:
    """Group lots by symbol and value them in instrument currency and USD."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for lot in positions:
        grouped.setdefault(lot["symbol"], []).append(lot)

    holdings: list[Holding] = []
    excluded: list[str] = []
    for symbol, lots in grouped.items():
        quote = quotes.get(symbol) or {}
        currency = str(quote.get("currency") or lots[0]["currency"]).strip().upper()
        quantity = sum(float(lot["quantity"]) for lot in lots)
        display_rate = _rate(rates, currency)
        cost_native, cost_usd = _lot_costs(lots, currency, rates)
        rate_ok = cost_native is not None and cost_usd is not None
        last = _positive_number(quote.get("price"))
        prior = _positive_number(prior_closes.get(symbol))

        market_native = quantity * last if rate_ok and last is not None else None
        market_usd = (
            market_native * display_rate
            if rate_ok and market_native is not None and display_rate is not None
            else None
        )
        change_pct = None
        daily_native = None
        if last is not None and prior is not None:
            change_pct = (last / prior - 1) * 100
            if rate_ok:
                daily_native = quantity * (last - prior)
        daily_usd = (
            daily_native * display_rate
            if rate_ok and daily_native is not None and display_rate is not None
            else None
        )
        unrealized_native = (
            market_native - cost_native
            if rate_ok and market_native is not None and cost_native is not None
            else None
        )
        unrealized_usd = (
            market_usd - cost_usd
            if rate_ok and market_usd is not None and cost_usd is not None
            else None
        )

        holdings.append(
            Holding(
                symbol=symbol,
                description=str(quote.get("description") or ""),
                currency=currency,
                quantity=quantity,
                last=last,
                change_pct=change_pct,
                cost_native=cost_native,
                cost_usd=cost_usd,
                market_native=market_native,
                market_usd=market_usd,
                avg_price=(
                    cost_native / quantity
                    if cost_native is not None and quantity > 0
                    else None
                ),
                daily_pnl_native=daily_native,
                daily_pnl_usd=daily_usd,
                unrealized_native=unrealized_native,
                unrealized_usd=unrealized_usd,
            )
        )
        if not rate_ok or last is None:
            excluded.append(symbol)

    excluded_set = set(excluded)
    included = [h for h in holdings if h.symbol not in excluded_set]
    total_cost = sum(h.cost_usd for h in included if h.cost_usd is not None)
    total_value = sum(h.market_usd for h in included if h.market_usd is not None)
    total_daily = (
        sum(h.daily_pnl_usd for h in included if h.daily_pnl_usd is not None)
        if included and all(h.daily_pnl_usd is not None for h in included)
        else None
    )
    total_unrealized = sum(
        h.unrealized_usd for h in included if h.unrealized_usd is not None
    )
    return PortfolioSummary(
        holdings=tuple(holdings),
        total_cost_usd=total_cost,
        total_value_usd=total_value,
        daily_pnl_usd=total_daily,
        unrealized_pnl_usd=total_unrealized,
        unrealized_pct=(
            total_unrealized / total_cost * 100 if total_cost > 0 else None
        ),
        excluded_symbols=tuple(excluded),
        usd_per_eur=_rate(rates, "EUR"),
    )


def backtest_allocation(summary: PortfolioSummary) -> tuple[list[str], list[float]]:
    """Turn priced holdings into weights that sum to 100 percent."""
    values: list[tuple[str, float]] = []
    excluded = set(summary.excluded_symbols)
    for holding in summary.holdings:
        if holding.symbol in excluded:
            continue
        if holding.market_usd is not None and holding.market_usd > 0:
            values.append((holding.symbol, holding.market_usd))
    if not values:
        return [], []
    total = sum(value for _, value in values)
    weights = [value / total * 100 for _, value in values]
    weights[-1] = 100.0 - sum(weights[:-1])
    return [symbol for symbol, _ in values], weights


def portfolio_snapshot(
    store: SQLiteStore,
    *,
    include_history: bool = True,
    fetch_fx: Callable[[str], dict[str, Any]] | None = None,
    fetch_history: Callable[[str], dict[str, Any]] | None = None,
) -> tuple[PortfolioSummary, list[str]]:
    """Build a valuation snapshot from stored lots, quotes and cached history."""
    positions = store.get_positions()
    symbols = list(dict.fromkeys(lot["symbol"] for lot in positions))
    quotes: dict[str, dict[str, Any]] = {}
    if symbols:
        rows, _, _ = store.get_stocks(
            filters={"symbol": {"values": symbols}}, page=1, page_size=len(symbols)
        )
        quotes = {row["symbol"]: row for row in rows}

    currencies = {"USD"}
    for lot in positions:
        currencies.add(str(lot["currency"]).strip().upper())
    for row in quotes.values():
        currency = str(row.get("currency") or "").strip().upper()
        if currency:
            currencies.add(currency)

    rates: dict[str, float | None] = {}
    stale: list[str] = []
    for currency in sorted(currencies & CONVERTIBLE_CURRENCIES):
        rates[currency], is_stale = usd_rate(store, currency, fetch=fetch_fx)
        if is_stale:
            stale.append(currency)

    # Headline totals show EUR even for USD-only portfolios. Reuse the last
    # cached rate without triggering a fetch that the holdings do not need.
    rates.setdefault("EUR", _positive_number(store.cache_get(FX_CACHE_KEY)))

    prior_closes: dict[str, float] = {}
    if include_history:
        for symbol in symbols:
            history = detail.load_history(store, symbol, "1Y", fetch=fetch_history)
            if len(history) >= 2:
                prior = _positive_number(history[-2].get("close"))
                if prior is not None:
                    prior_closes[symbol] = prior

    return (
        build_portfolio_summary(positions, quotes, prior_closes, rates),
        stale,
    )
