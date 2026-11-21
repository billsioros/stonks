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
