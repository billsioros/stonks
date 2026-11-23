"""StockAnalysis.com provider: bulk screener data for the local store.

The screener's filter endpoints are client-side; the two JSON endpoints below
serve the whole universe and every data point without any preset filtering.
"""

from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable
from typing import Any

from stonks.treasury import fetch_treasury_yield_pct
from stonks.valuation import (
    DCF_DISCOUNT_RATE,
    dcf_discount_rate,
    dcf_fair_value,
    evaluate_cyclical_peak_risk,
    evaluate_valuation_triangulation,
    lynch_fair_value,
    upside_pct,
)

BASE_URL = "https://stockanalysis.com/_api/endpoints/screener"
INITIAL_URL = f"{BASE_URL}/initial?type=stock&countryCode=&format=compact"
DATA_POINTS_URL = f"{BASE_URL}/data-points?type=s&ids={{ids}}"

REQUEST_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0  # seconds; doubled on each retry
REQUEST_TIMEOUT = 60

# `s` must not be requested here: it collapses the response to a single null
# row. Symbol, name and industry come from the initial endpoint instead.
DATA_POINT_IDS = (
    "marketCap",
    "peRatio",
    "pbRatio",
    "psRatio",
    "dividendYield",
    "grossMargin",
    "operatingMargin",
    "profitMargin",
    "roa",
    "roe",
    "roic",
    "currentRatio",
    "debtEquity",
    "fcfMargin",
    "revenueGrowth5Y",
    "epsGrowth5Y",
    "beta",
    "high52",
    "low52",
    "price",
    "pegRatio",
    "evEbitda",
    "fcfPerShare",
    "bvPerShare",
    "tangibleBookValuePerShare",
    "assetTurnover",
    "eps",
    "epsGrowth10Y",
    "revenueGrowth3Y",
    "epsGrowth3Y",
    "netIncome",
    "fcf",
    "fcfGrowth5Y",
    "netIncomeGrowth5Y",
    "cagr5y",
    "cagr10y",
    "cagr15y",
    "roa5y",
    "roe5y",
    "roic5y",
    "sharesInsiders",
    "industry",
    "shortFloat",
    "analystRatings",
    "priceTargetChange",
    "exchange",
    "priceCurrency",
    "n",
)

EXCHANGE_MAP = {
    "NASDAQ": "NMS",
    "NYSE": "NYQ",
    "AMEX": "ASE",
    "NYSE AMERICAN": "ASE",
}


def _identity(value: Any) -> Any:
    return value


def _millions(value: Any) -> Any:
    """StockAnalysis reports cash-flow figures in dollars; the store uses millions."""
    return value / 1e6 if isinstance(value, (int, float)) else value


def _fraction(value: Any) -> Any:
    """StockAnalysis reports insider ownership in percent; the store uses a fraction."""
    return value / 100 if isinstance(value, (int, float)) else value


def _exchange(value: Any) -> Any:
    return EXCHANGE_MAP.get(value, value)


# Local column -> (data-point id, unit conversion).
DATA_POINT_MAP: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "market_cap": ("marketCap", _identity),
    "pe_ratio": ("peRatio", _identity),
    "pb_ratio": ("pbRatio", _identity),
    "ps_ratio": ("psRatio", _identity),
    "dividend_yield_pct": ("dividendYield", _identity),
    "gross_margin_pct": ("grossMargin", _identity),
    "operating_margin_pct": ("operatingMargin", _identity),
    "net_margin_pct": ("profitMargin", _identity),
    "roa_pct": ("roa", _identity),
    "roe_pct": ("roe", _identity),
    "roic_pct": ("roic", _identity),
    "current_ratio": ("currentRatio", _identity),
    "debt_to_equity": ("debtEquity", _identity),
    "fcf_margin_pct": ("fcfMargin", _identity),
    "revenue_growth_5y_pct": ("revenueGrowth5Y", _identity),
    "eps_growth_5y_pct": ("epsGrowth5Y", _identity),
    "beta": ("beta", _identity),
    "week_52_high": ("high52", _identity),
    "week_52_low": ("low52", _identity),
    "price": ("price", _identity),
    "peg_ratio": ("pegRatio", _identity),
    "ev_to_ebitda": ("evEbitda", _identity),
    "free_cash_flow_per_share": ("fcfPerShare", _identity),
    "book_value_per_share": ("bvPerShare", _identity),
    "tangible_book_value_per_share": ("tangibleBookValuePerShare", _identity),
    "asset_turnover": ("assetTurnover", _identity),
    "eps_ttm": ("eps", _identity),
    "revenue_growth_3y_pct": ("revenueGrowth3Y", _identity),
    "eps_growth_3y_pct": ("epsGrowth3Y", _identity),
    "net_income": ("netIncome", _millions),
    "free_cash_flow": ("fcf", _millions),
    "fcf_growth_5y_pct": ("fcfGrowth5Y", _identity),
    "net_income_growth_5y_pct": ("netIncomeGrowth5Y", _identity),
    "return_cagr_5y_pct": ("cagr5y", _identity),
    "return_cagr_10y_pct": ("cagr10y", _identity),
    "return_cagr_15y_pct": ("cagr15y", _identity),
    "roa_5y_avg_pct": ("roa5y", _identity),
    "roe_5y_avg_pct": ("roe5y", _identity),
    "roic_5y_avg_pct": ("roic5y", _identity),
    "shares_insiders_pct": ("sharesInsiders", _fraction),
    "shares_insiders_percent": ("sharesInsiders", _identity),
    "short_pct": ("shortFloat", _identity),
    "rating": ("analystRatings", _identity),
    "pt_upside_pct": ("priceTargetChange", _identity),
    "exchange": ("exchange", _exchange),
    "currency": ("priceCurrency", _identity),
}

UNIVERSE_COLUMNS = ("symbol", "description", "industry")
SUPPORTED_COLUMNS = set(UNIVERSE_COLUMNS) | set(DATA_POINT_MAP)


def fetch_json(url: str) -> dict[str, Any]:
    """GET a JSON payload, retrying transient transport errors."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; stonks)"}
    )
    last_error: Exception | None = None
    for attempt in range(REQUEST_ATTEMPTS):
        try:
            with urllib.request.urlopen(  # nosec B310 - URLs are fixed https constants
                request, timeout=REQUEST_TIMEOUT
            ) as response:
                return json.load(response)
        except (OSError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < REQUEST_ATTEMPTS:
                time.sleep(RETRY_BASE_DELAY * 2**attempt)
    raise last_error  # type: ignore[misc]


def fetch_universe(fetch: Callable[[str], dict[str, Any]] | None = None) -> list[dict]:
    """Fetch the full stock universe with symbol, name and industry."""
    payload = (fetch or fetch_json)(INITIAL_URL)
    data = payload["data"]
    positions = {name: index for index, name in enumerate(data["columns"])}
    return [
        {
            "symbol": row[positions["s"]],
            "description": row[positions["n"]],
            "industry": row[positions["industry"]],
        }
        for row in data["rows"]
    ]


def fetch_metrics(
    fetch: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fetch every metric data point, keyed by symbol."""
    url = DATA_POINTS_URL.format(ids="+".join(DATA_POINT_IDS))
    return (fetch or fetch_json)(url)["data"]["data"]


def build_rows(
    universe: list[dict],
    metrics: dict[str, dict[str, Any]],
    discount_rate: float = DCF_DISCOUNT_RATE,
) -> list[dict[str, Any]]:
    """Merge universe and metrics into rows shaped for SQLiteStore.save_stock."""
    rows = []
    for base in universe:
        point = metrics.get(base["symbol"])
        if point is None:
            continue
        row: dict[str, Any] = dict(base)
        if not row["industry"]:
            row["industry"] = point.get("industry")
        for column, (field, convert) in DATA_POINT_MAP.items():
            value = point.get(field)
            row[column] = convert(value) if value is not None else None
        _add_valuation(row, point, discount_rate)
        _add_investment_signals(row)
        rows.append(row)
    return rows


def _add_valuation(
    row: dict[str, Any], point: dict[str, Any], discount_rate: float
) -> None:
    """Attach the GuruFocus-style fair values to a store row in place."""
    price = row.get("price")
    dcf = dcf_fair_value(point.get("eps"), point.get("epsGrowth10Y"), discount_rate)
    lynch = lynch_fair_value(point.get("eps"), point.get("epsGrowth5Y"))
    row["dcf_fair_value"] = dcf
    row["dcf_upside_pct"] = upside_pct(dcf, price)
    row["lynch_fair_value"] = lynch
    row["lynch_upside_pct"] = upside_pct(lynch, price)


def _add_investment_signals(row: dict[str, Any]) -> None:
    """Attach the cyclicality flag and the valuation-consensus columns."""
    risk = evaluate_cyclical_peak_risk(
        row.get("industry"),
        row.get("ev_to_ebitda"),
        row.get("roic_5y_avg_pct"),
        row.get("fcf_growth_5y_pct"),
    )
    verdict, capped = evaluate_valuation_triangulation(
        row.get("dcf_upside_pct"),
        row.get("lynch_upside_pct"),
        row.get("pt_upside_pct"),
        row.get("peg_ratio"),
        risk,
    )
    row["cyclical_peak_risk"] = risk
    row["valuation_triangulation"] = verdict
    row["valuation_upside_capped_pct"] = capped


def current_discount_rate() -> float:
    """DCF discount rate for this sync, from the live ten-year Treasury yield."""
    return dcf_discount_rate(fetch_treasury_yield_pct())


def fetch_rows(
    fetch: Callable[[str], dict[str, Any]] | None = None,
    discount_rate: float | None = None,
) -> list[dict[str, Any]]:
    """Fetch both payloads and return store-ready rows for the whole universe.

    Args:
        fetch: Optional JSON fetcher, for tests.
        discount_rate: DCF discount rate as a fraction; looked up from the
            current Treasury yield when omitted.
    """
    rate = current_discount_rate() if discount_rate is None else discount_rate
    return build_rows(fetch_universe(fetch), fetch_metrics(fetch), rate)
