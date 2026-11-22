"""Turn resolved detail payloads into display-ready structures.

Everything here is pure: the payloads come from ``stonks.detail.load_page`` and
no value is invented — a field the provider omits stays ``None``.
"""

from __future__ import annotations

from typing import Any

SITE_URL = "https://stockanalysis.com"

# Payload field -> key used by the view layer.
_OVERVIEW_FIELDS: tuple[tuple[str, str], ...] = (
    ("marketCap", "market_cap"),
    ("peRatio", "pe_ratio"),
    ("forwardPE", "forward_pe"),
    ("eps", "eps"),
    ("revenue", "revenue"),
    ("revenue_type", "revenue_type"),
    ("revenueGrowth", "revenue_growth"),
    ("netIncome", "net_income"),
    ("netIncomeGrowth", "net_income_growth"),
    ("sharesOut", "shares_out"),
    ("beta", "beta"),
    ("dividend", "dividend"),
    ("exDividendDate", "ex_dividend_date"),
    ("analysts", "analyst_rating"),
    ("target", "analyst_target"),
    ("earningsDate", "earnings_date"),
    ("earningsDateLabel", "earnings_date_label"),
    ("description", "summary"),
)


# Statistics sections carry no title in the payload, so the order and labels
# live here; sections absent from this tuple are ignored.
STATISTICS_ORDER: tuple[tuple[str, str], ...] = (
    ("valuation", "Valuation"),
    ("dates", "Dates"),
    ("shares", "Shares"),
    ("ratios", "Ratios"),
    ("evRatios", "EV Ratios"),
    ("financialPosition", "Financial Position"),
    ("financialEfficiency", "Financial Efficiency"),
    ("taxes", "Taxes"),
    ("stockPrice", "Stock Price"),
    ("shortSelling", "Short Selling"),
    ("incomeStatement", "Income Statement"),
    ("balanceSheet", "Balance Sheet"),
    ("cashFlow", "Cash Flow"),
    ("margins", "Margins"),
    ("dividends", "Dividends"),
    ("analystForecasts", "Analyst Forecasts"),
    ("stockSplits", "Stock Splits"),
    ("scores", "Scores"),
    ("fairValue", "Fair Value"),
)


def _text(value: Any) -> str | None:
    """Provider strings pass through; empty or non-string values become None."""
    if value is None or value == "":
        return None
    return value if isinstance(value, str) else str(value)


def parse_overview(data: dict[str, Any]) -> dict[str, Any]:
    """Parse the symbol overview payload into quote fields, info rows and news."""
    out: dict[str, Any] = {
        local: _text(data.get(source)) for source, local in _OVERVIEW_FIELDS
    }

    out["info"] = [
        {
            "label": row.get("t"),
            "value": row.get("v"),
            "url": f"{SITE_URL}/{row['u']}" if row.get("u") else None,
        }
        for row in data.get("infoTable") or []
        if isinstance(row, dict)
    ]

    news = data.get("news")
    items = news.get("data") if isinstance(news, dict) else None
    out["news"] = [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "source": item.get("source"),
            "ago": item.get("ago"),
            "summary": item.get("text"),
        }
        for item in (items or [])[:10]
        if isinstance(item, dict)
    ]
    return out


def parse_history(payload: Any, *, adjusted: bool = False) -> list[dict[str, Any]]:
    """Parse a history payload into ``{date, close}`` rows, oldest first.

    The provider serves newest first; rows without a usable date or close are
    dropped rather than interpolated. ``adjusted`` prefers the dividend-adjusted
    close (``a``), falling back to the raw close for bars that lack it — a
    backtest needs total return, a price chart wants the traded price.
    """
    rows = payload.get("data") if isinstance(payload, dict) else payload
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        date = row.get("t")
        close = (row.get("a") if adjusted else None) or row.get("c")
        if not isinstance(date, str) or not date:
            continue
        if isinstance(close, bool) or not isinstance(close, (int, float)):
            continue
        out.append({"date": date, "close": float(close)})
    out.sort(key=lambda entry: entry["date"])
    return out


def parse_statistics(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse the statistics payload into titled sections in display order."""
    sections: list[dict[str, Any]] = []
    for key, title in STATISTICS_ORDER:
        section = data.get(key)
        if not isinstance(section, dict):
            continue
        items = [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "value": item.get("value"),
                "hover": item.get("hover"),
            }
            for item in section.get("data") or []
            if isinstance(item, dict)
        ]
        if not items:
            continue
        sections.append(
            {"key": key, "title": title, "text": section.get("text"), "items": items}
        )
    return sections


_ESTIMATE_FIELDS = ("epsThis", "epsNext", "revenueThis", "revenueNext")
_RATING_FIELDS = (
    ("firm", "firm"),
    ("analyst", "analyst"),
    ("action_rt", "action"),
    ("pt_now", "target_now"),
    ("pt_old", "target_old"),
    ("rating_new", "rating_new"),
    ("rating_old", "rating_old"),
    ("date", "date"),
    ("time", "time"),
)


def parse_forecast(data: dict[str, Any]) -> dict[str, Any]:
    """Parse the forecast payload into targets, estimates and analyst actions."""
    raw_targets = data.get("targets")
    targets = None
    if isinstance(raw_targets, dict) and raw_targets:
        targets = {
            key: raw_targets.get(key)
            for key in ("low", "median", "average", "high", "count", "updated")
        }

    raw_stats = (data.get("estimates") or {}).get("stats") or {}
    estimates: dict[str, dict[str, Any]] = {}
    for period in ("annual", "quarterly"):
        period_stats = raw_stats.get(period) or {}
        estimates[period] = {
            field: {
                "last": period_stats[field].get("last"),
                "this": period_stats[field].get("this"),
                "growth": period_stats[field].get("growth"),
            }
            for field in _ESTIMATE_FIELDS
            if isinstance(period_stats.get(field), dict)
        }

    raw_ratings = data.get("currentRatings")
    current_ratings = None
    if isinstance(raw_ratings, dict) and raw_ratings:
        current_ratings = {
            key: raw_ratings.get(key)
            for key in (
                "consensus",
                "score",
                "count",
                "strongBuy",
                "buy",
                "hold",
                "sell",
                "strongSell",
            )
        }

    ratings = [
        {local: item.get(source) for source, local in _RATING_FIELDS}
        for item in data.get("ratings") or []
        if isinstance(item, dict)
    ]

    return {
        "targets": targets,
        "estimates": estimates,
        "current_ratings": current_ratings,
        "recommendations": [
            item for item in data.get("recommendations") or [] if isinstance(item, dict)
        ],
        "ratings": ratings,
    }


def _statement_value(value: Any) -> float | None:
    """Keep real numbers; ``[PRO]`` and other placeholders become None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def parse_statement(data: dict[str, Any]) -> dict[str, Any]:
    """Parse a financial statement payload into periods and ordered rows."""
    financial = data.get("financialData") or {}
    datekeys = financial.get("datekey") or []
    fiscal_years = financial.get("fiscalYear") or []
    fiscal_quarters = financial.get("fiscalQuarter") or []
    quarterly = data.get("period") == "quarterly"

    periods: list[dict[str, Any]] = []
    for index, key in enumerate(datekeys):
        year = fiscal_years[index] if index < len(fiscal_years) else None
        quarter = fiscal_quarters[index] if index < len(fiscal_quarters) else None
        is_ttm = key == "TTM"
        if is_ttm:
            label = "TTM"
        elif quarterly and quarter and year:
            label = f"{quarter} {year}"
        elif not quarterly and year:
            label = f"FY{year}"
        else:
            label = str(key)
        periods.append({"key": key, "label": label, "is_ttm": is_ttm})

    rows: list[dict[str, Any]] = []
    for entry in data.get("map") or []:
        if not isinstance(entry, dict):
            continue
        raw = financial.get(entry.get("id")) or []
        values = [_statement_value(value) for value in raw[: len(periods)]]
        values += [None] * (len(periods) - len(values))
        rows.append(
            {"id": entry.get("id"), "label": entry.get("title"), "values": values}
        )

    return {
        "statement": data.get("statement"),
        "period": data.get("period"),
        "periods": periods,
        "rows": rows,
    }
