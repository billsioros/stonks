"""Yahoo Finance provider: server-side screening plus cached fundamental enrichment."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pandas as pd
import yfinance as yf
from yfinance import EquityQuery

from stonks.config import YAHOO_MAX_WORKERS, YAHOO_PAGE_SIZE
from stonks.presets import POPULAR_SCREENS

logger = logging.getLogger(__name__)

# Stonks column -> (Yahoo screener field, multiplier from Stonks units to Yahoo units)
SCREENER_FIELD_MAP: dict[str, tuple[str, float]] = {
    "market_cap": ("intradaymarketcap", 1e6),
    "pe_ratio": ("peratio.lasttwelvemonths", 1.0),
    "pb_ratio": ("pricebookratio.quarterly", 1.0),
    "dividend_yield_pct": ("dividendyield", 1.0),
    "roe_pct": ("returnonequity.lasttwelvemonths", 1.0),
    "gross_margin_pct": ("grossprofitmargin.lasttwelvemonths", 1.0),
    "debt_to_equity": ("totaldebtequity.lasttwelvemonths", 1.0),
    "current_ratio": ("currentratio.lasttwelvemonths", 1.0),
    "roic_pct": ("returnontotalcapital.lasttwelvemonths", 1.0),
    "shares_insiders_pct": ("pctheldinsider", 1.0),
    "free_cash_flow": ("leveredfreecashflow.lasttwelvemonths", 1e6),
    "net_income": ("netincomeis.lasttwelvemonths", 1e6),
}

_ENUM_FIELDS = {"exchange": "exchange", "currency": "currency"}

_DERIVED_COLUMNS = (
    "roa_pct",
    "roe_pct",
    "roic_pct",
    "gross_margin_pct",
    "operating_margin_pct",
    "net_margin_pct",
    "current_ratio",
    "debt_to_equity",
    "long_term_debt_to_equity",
    "free_cash_flow",
    "net_income",
    "shares_insiders_pct",
    "eps_ttm",
    "peg_ratio",
    "ev_to_ebitda",
    "ps_ratio",
    "book_value_per_share",
    "tangible_book_value_per_share",
    "short_pct",
    "revenue_growth_5y_pct",
    "eps_growth_5y_pct",
    "fcf_growth_5y_pct",
    "net_income_growth_5y_pct",
    "return_cagr_5y_pct",
    "return_cagr_10y_pct",
    "return_cagr_15y_pct",
    "roa_5y_avg_pct",
    "roe_5y_avg_pct",
    "roic_5y_avg_pct",
)


def build_screener_query(filters: dict[str, dict[str, Any]]) -> EquityQuery:
    """Translate Stonks min/max filters into a Yahoo screener query."""
    operands: list[EquityQuery] = [
        EquityQuery("eq", ["region", "us"]),
        EquityQuery("gt", ["intradaymarketcap", 0]),
    ]
    for column, bounds in filters.items():
        if column in SCREENER_FIELD_MAP:
            field, multiplier = SCREENER_FIELD_MAP[column]
            if bounds.get("min") is not None:
                operands.append(EquityQuery("gt", [field, bounds["min"] * multiplier]))
            if bounds.get("max") is not None:
                operands.append(EquityQuery("lt", [field, bounds["max"] * multiplier]))
        elif column in _ENUM_FIELDS and bounds.get("values"):
            for value in bounds["values"]:
                operands.append(EquityQuery("eq", [_ENUM_FIELDS[column], value]))
    return EquityQuery("and", operands)


def paginate(
    query: EquityQuery,
    page_size: int = YAHOO_PAGE_SIZE,
    screen_fn: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch every page of a screener query and normalize the quote payloads."""
    fetch = screen_fn or screen
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        payload = fetch(
            query, offset=offset, size=page_size, sortField="ticker", sortAsc=False
        )
        quotes = payload.get("quotes") or []
        rows.extend(normalize_quote(quote) for quote in quotes)
        total = payload.get("total")
        if len(quotes) < page_size or (
            total is not None and offset + len(quotes) >= total
        ):
            break
        offset += len(quotes)
    return rows


def screen(query: EquityQuery, **kwargs: Any) -> dict[str, Any]:
    """Thin wrapper around yfinance.screen so tests can patch one symbol."""
    return yf.screen(query, **kwargs)


def normalize_quote(raw: dict[str, Any]) -> dict[str, Any]:
    """Map a Yahoo quote payload to Stonks columns (derived columns omitted)."""
    row: dict[str, Any] = {"symbol": raw.get("symbol")}
    mapping = {
        "description": raw.get("shortName") or raw.get("longName"),
        "exchange": raw.get("exchange"),
        "mic": raw.get("fullExchangeName"),
        "currency": raw.get("currency"),
        "market_cap": _scaled(raw.get("marketCap"), 1 / 1e6),
        "pe_ratio": raw.get("trailingPE"),
        "pb_ratio": raw.get("priceToBook"),
        "dividend_yield_pct": raw.get("dividendYield"),
        "price": raw.get("regularMarketPrice"),
        "week_52_high": raw.get("fiftyTwoWeekHigh"),
        "week_52_low": raw.get("fiftyTwoWeekLow"),
        "beta": raw.get("beta"),
        "eps_ttm": raw.get("epsTrailingTwelveMonths"),
        "book_value_per_share": raw.get("bookValue"),
        "rating": raw.get("averageAnalystRating"),
    }
    row.update({key: value for key, value in mapping.items() if value is not None})
    return row


def _scaled(value: Any, factor: float) -> float | None:
    return value * factor if isinstance(value, (int, float)) else None


def _pct(value: Any) -> float | None:
    return _scaled(value, 100.0)


def _row(statement: Any, label: str) -> pd.Series | None:
    if statement is None or label not in statement.index:
        return None
    series = statement.loc[label]
    return series.dropna() if isinstance(series, pd.Series) else None


def _first_row(statement: Any, *labels: str) -> pd.Series | None:
    for label in labels:
        series = _row(statement, label)
        if series is not None and not series.empty:
            return series
    return None


def _cagr_from_series(series: pd.Series | None, years: int) -> float | None:
    if series is None or len(series) < 2:
        return None
    ordered = series.sort_index()
    first, last = ordered.iloc[0], ordered.iloc[-1]
    if not (isinstance(first, (int, float)) and isinstance(last, (int, float))):
        return None
    span = min(len(series) - 1, years)
    if first <= 0 or last <= 0 or span <= 0:
        return None
    return ((last / first) ** (1 / span) - 1) * 100


def _price_cagr(history: Any, years: int) -> float | None:
    if history is None or not isinstance(history, pd.DataFrame) or history.empty:
        return None
    column = "Close" if "Close" in history.columns else "close"
    if column not in history.columns:
        return None
    closes = history[column].dropna()
    if closes.empty:
        return None
    target = closes.index[-1] - pd.DateOffset(years=years)
    start = closes.asof(target)
    end = closes.iloc[-1]
    if pd.isna(start) or pd.isna(end) or start <= 0 or end <= 0:
        return None
    return ((end / start) ** (1 / years) - 1) * 100


def derive_metrics(
    info: dict[str, Any] | None,
    history: Any,
    financials: Any,
    balance_sheet: Any,
    cashflow: Any,
) -> dict[str, Any]:
    """Compute Stonks metric columns from Yahoo fundamentals and price history."""
    result: dict[str, Any] = {column: None for column in _DERIVED_COLUMNS}

    if isinstance(info, dict):
        result.update(
            {
                "gross_margin_pct": _pct(info.get("grossMargins")),
                "operating_margin_pct": _pct(info.get("operatingMargins")),
                "net_margin_pct": _pct(info.get("profitMargins")),
                "roa_pct": _pct(info.get("returnOnAssets")),
                "roe_pct": _pct(info.get("returnOnEquity")),
                "debt_to_equity": _scaled(info.get("debtToEquity"), 0.01),
                "current_ratio": info.get("currentRatio"),
                "free_cash_flow": _scaled(info.get("freeCashflow"), 1 / 1e6),
                "shares_insiders_pct": info.get("heldPercentInsiders"),
                "eps_ttm": info.get("trailingEps"),
                "peg_ratio": info.get("pegRatio") or info.get("trailingPegRatio"),
                "ev_to_ebitda": info.get("enterpriseToEbitda"),
                "ps_ratio": info.get("priceToSalesTrailing12Months"),
                "book_value_per_share": info.get("bookValue"),
                "tangible_book_value_per_share": info.get("tangibleBookValue"),
                "short_pct": _pct(info.get("shortPercentOfFloat")),
            }
        )

    for years in (5, 10, 15):
        result[f"return_cagr_{years}y_pct"] = _price_cagr(history, years)

    net_income = _first_row(financials, "Net Income", "Net Income Common Stockholders")
    total_revenue = _row(financials, "Total Revenue")
    operating_income = _first_row(financials, "Operating Income", "EBIT")
    basic_eps = _first_row(financials, "Basic EPS", "Net Income")
    total_assets = _row(balance_sheet, "Total Assets")
    total_equity = _first_row(
        balance_sheet, "Total Equity Gross Minority Interest", "Stockholders Equity"
    )
    total_debt = _row(balance_sheet, "Total Debt")
    free_cash_flow = _row(cashflow, "Free Cash Flow")

    if net_income is not None:
        latest = net_income.sort_index().iloc[-1]
        if isinstance(latest, (int, float)):
            result["net_income"] = latest / 1e6
    if total_revenue is not None and operating_income is not None:
        aligned = operating_income.reindex(total_revenue.index).dropna()
        revenues = total_revenue.reindex(aligned.index)
        if not revenues.empty and (revenues != 0).all():
            result["operating_margin_pct"] = float((aligned / revenues).iloc[-1] * 100)

    for key, number, denom in (
        ("roa_5y_avg_pct", net_income, total_assets),
        ("roe_5y_avg_pct", net_income, total_equity),
    ):
        if number is not None and denom is not None:
            aligned = number.reindex(denom.index).dropna().tail(5)
            values = denom.reindex(aligned.index)
            if not values.empty and (values != 0).all():
                result[key] = float((aligned / values).mean() * 100)
    if net_income is not None and total_debt is not None and total_equity is not None:
        aligned = net_income.reindex(total_equity.index).dropna().tail(5)
        debt = total_debt.reindex(aligned.index)
        equity = total_equity.reindex(aligned.index)
        if not debt.empty and ((debt + equity) != 0).all():
            result["roic_5y_avg_pct"] = float((aligned / (debt + equity)).mean() * 100)

    result["revenue_growth_5y_pct"] = _cagr_from_series(total_revenue, 5)
    result["eps_growth_5y_pct"] = _cagr_from_series(basic_eps, 5)
    result["net_income_growth_5y_pct"] = _cagr_from_series(net_income, 5)
    result["fcf_growth_5y_pct"] = _cagr_from_series(free_cash_flow, 5)
    if result["free_cash_flow"] is None and free_cash_flow is not None:
        latest_fcf = free_cash_flow.sort_index().iloc[-1]
        if isinstance(latest_fcf, (int, float)):
            result["free_cash_flow"] = latest_fcf / 1e6
    return result


def enrich_symbol(
    symbol: str, ticker_factory: Callable[[str], Any] | None = None
) -> dict[str, Any]:
    """Fetch one symbol's fundamentals; individual Yahoo failures yield missing fields."""
    result: dict[str, Any] = {"symbol": symbol}
    try:
        ticker = (ticker_factory or yf.Ticker)(symbol)
    except Exception as exc:  # noqa: BLE001 - Yahoo clients fail in many ways
        logger.warning("Cannot create ticker for %s: %s", symbol, exc)
        return result

    def safe_fetch(name: str, fetch: Callable[[], Any]) -> Any:
        try:
            return fetch()
        except Exception as exc:  # noqa: BLE001 - keep cached data on any provider error
            logger.warning("%s: failed to fetch %s: %s", symbol, name, exc)
            return None

    info = safe_fetch("info", lambda: ticker.info)
    history = safe_fetch(
        "history",
        lambda: ticker.history(period="15y", interval="1mo", auto_adjust=True),
    )
    financials = safe_fetch("financials", lambda: ticker.financials)
    balance_sheet = safe_fetch("balance_sheet", lambda: ticker.balance_sheet)
    cashflow = safe_fetch("cashflow", lambda: ticker.cashflow)
    result.update(derive_metrics(info, history, financials, balance_sheet, cashflow))
    return result


def preset_candidate_rows(
    presets: list[dict[str, Any]] = POPULAR_SCREENS,
    page_size: int = YAHOO_PAGE_SIZE,
    screen_fn: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Union the candidate symbols produced by every preset's server-side filters."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for preset in presets:
        query = build_screener_query(preset.get("filters", {}))
        for row in paginate(query, page_size=page_size, screen_fn=screen_fn):
            symbol = row["symbol"]
            if symbol not in seen:
                seen.add(symbol)
                rows.append(row)
    return rows


def required_preset_columns(
    presets: list[dict[str, Any]] = POPULAR_SCREENS,
) -> set[str]:
    """All filter columns that must be available locally for the given presets."""
    return {column for preset in presets for column in preset.get("filters", {})}


def _enrich_one(
    row: dict[str, Any],
    required_columns: set[str],
    fetch: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    if not (required_columns - row.keys()):
        return row
    try:
        fetched = fetch(row["symbol"])
        return {
            **row,
            **{key: value for key, value in fetched.items() if key in required_columns},
        }
    except Exception as exc:  # noqa: BLE001 - one bad symbol must not abort the sync
        logger.warning("Enrichment failed for %s: %s", row.get("symbol"), exc)
        return row


def enrich_rows(
    rows: list[dict[str, Any]],
    required_columns: set[str],
    enrich_fn: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Enrich only rows missing required columns, preserving values already present."""
    fetch = enrich_fn or enrich_symbol
    if len(rows) <= 1:
        return [_enrich_one(row, required_columns, fetch) for row in rows]
    with ThreadPoolExecutor(max_workers=YAHOO_MAX_WORKERS) as pool:
        return list(
            pool.map(lambda row: _enrich_one(row, required_columns, fetch), rows)
        )
