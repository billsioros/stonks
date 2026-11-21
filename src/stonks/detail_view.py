"""Streamlit rendering for the per-symbol detail page.

Only the selected section is fetched and rendered. ``st.tabs`` would evaluate
every body on each rerun, which means five payload requests per interaction;
a segmented control keeps it to one.
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
import streamlit as st

from stonks.detail import STATEMENTS, load_page
from stonks.detail_parse import (
    parse_forecast,
    parse_overview,
    parse_statement,
    parse_statistics,
)
from stonks.store import SQLiteStore

SECTIONS = ("Overview", "Financials", "Statistics", "Metrics", "Forecast")
STATEMENT_LABELS = {
    "income-statement": "Income Statement",
    "balance-sheet": "Balance Sheet",
    "cash-flow-statement": "Cash Flow",
    "ratios": "Ratios",
}
METRICS_KEYS = ("ratios", "evRatios", "margins", "shares")


# ── Formatting helpers ───────────────────────────────────────────────


def format_compact(value: Any) -> str:
    """Format a number, scaling large magnitudes; anything else is a dash."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    magnitude = abs(value)
    if magnitude >= 1e12:
        return f"{value / 1e12:.2f}T"
    if magnitude >= 1e9:
        return f"{value / 1e9:.2f}B"
    if magnitude >= 1e6:
        return f"{value / 1e6:.2f}M"
    if magnitude >= 1e3:
        return f"{value / 1e3:.2f}K"
    return f"{value:.2f}"


def format_cell(value: Any) -> str:
    """Format a provider value for display; placeholders and blanks become a dash."""
    if value is None:
        return "—"
    if isinstance(value, str):
        return "—" if value.strip() in ("", "[PRO]") else value
    if isinstance(value, bool):
        return "✓" if value else "✗"
    if isinstance(value, (int, float)):
        return format_compact(value)
    return str(value)


def range_position(
    price: float | None, low: float | None, high: float | None
) -> float | None:
    """Where `price` sits in the 52-week range, as 0..1."""
    if price is None or low is None or high is None or low >= high:
        return None
    return max(0.0, min(1.0, (price - low) / (high - low)))


def yoy_pct(current: float | None, prior: float | None) -> float | None:
    """Percent change against `prior`; None when it cannot be computed."""
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior) * 100


def _signed_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%"


def _as_of(epoch: float | None) -> str:
    if epoch is None:
        return "unknown"
    return time.strftime("%H:%M", time.localtime(epoch))


# ── Page ─────────────────────────────────────────────────────────────


def _clear_cache(store: SQLiteStore, symbol: str) -> None:
    """Drop every cached payload for this symbol so the next render refetches."""
    pages = [
        ("overview", "-", "annual"),
        ("statistics", "-", "annual"),
        ("forecast", "-", "annual"),
    ]
    for statement in STATEMENTS:
        for period in ("annual", "quarterly"):
            pages.append(("financials", statement, period))
    from stonks.detail import cache_key

    for page, statement, period in pages:
        store.cache_delete(cache_key(symbol, page, statement=statement, period=period))


def _store_row(store: SQLiteStore, symbol: str) -> dict[str, Any]:
    rows, _, _ = store.get_stocks(filters={"symbol": {"values": [symbol]}}, page_size=1)
    return rows[0] if rows else {}


def render_detail_page(store: SQLiteStore, symbol: str) -> None:
    """Render the detail page for one symbol."""
    symbol = symbol.strip().upper()
    overview_data, fetched_at = load_page(store, symbol, "overview")
    if overview_data is None:
        st.error(f"No data for {symbol}")
        return

    overview = parse_overview(overview_data)
    row = _store_row(store, symbol)

    st.markdown(
        f'<div class="section-header">{symbol} · '
        f"{(row.get('description') or symbol).upper()}</div>",
        unsafe_allow_html=True,
    )
    stamp_col, refresh_col = st.columns([4, 1])
    with stamp_col:
        st.caption(f"as of {_as_of(fetched_at)} · source StockAnalysis.com")
    with refresh_col:
        if st.button("🔄 Refresh", key=f"detail_refresh_{symbol}"):
            _clear_cache(store, symbol)
            st.rerun()

    section = st.segmented_control(
        "Section",
        options=list(SECTIONS),
        default="Overview",
        key=f"detail_section_{symbol}",
        label_visibility="collapsed",
    )
    section = section or "Overview"

    if section == "Overview":
        _render_overview(store, symbol, overview, row)
    elif section == "Financials":
        _render_financials(store, symbol)
    elif section == "Statistics":
        _render_statistics(store, symbol)
    elif section == "Metrics":
        _render_metrics(store, symbol)
    else:
        _render_forecast(store, symbol)


# ── Overview ─────────────────────────────────────────────────────────


def _render_overview(
    store: SQLiteStore,
    symbol: str,
    overview: dict[str, Any],
    row: dict[str, Any],
) -> None:
    price = row.get("price")
    low, high = row.get("week_52_low"), row.get("week_52_high")
    position = range_position(price, low, high)

    cols = st.columns(4)
    cols[0].metric("Price", format_cell(price))
    cols[1].metric("52-week range", f"{format_cell(low)} – {format_cell(high)}")
    cols[2].metric(
        "Range position", "—" if position is None else f"{position * 100:.0f}%"
    )
    cols[3].metric("Market cap", format_cell(overview.get("market_cap")))

    st.markdown('<div class="section-header">Signals</div>', unsafe_allow_html=True)
    signals = [
        ("Analyst rating", format_cell(row.get("rating"))),
        ("Target upside", format_cell(row.get("pt_upside_pct"))),
        ("DCF upside", format_cell(row.get("dcf_upside_pct"))),
        ("Lynch upside", format_cell(row.get("lynch_upside_pct"))),
        ("Short float", format_cell(row.get("short_pct"))),
        ("Forward P/E", format_cell(overview.get("forward_pe"))),
    ]
    cols = st.columns(len(signals))
    for col, (label, value) in zip(cols, signals):
        col.markdown(f"**{label}**<br>{value}", unsafe_allow_html=True)

    st.markdown('<div class="section-header">Key data</div>', unsafe_allow_html=True)
    key_rows = [
        ("Revenue (TTM)", overview.get("revenue")),
        ("Revenue growth", overview.get("revenue_growth")),
        ("Net income (TTM)", overview.get("net_income")),
        ("Net income growth", overview.get("net_income_growth")),
        ("EPS (TTM)", overview.get("eps")),
        ("P/E", overview.get("pe_ratio")),
        ("Shares out", overview.get("shares_out")),
        ("Beta", overview.get("beta")),
        ("Dividend", overview.get("dividend")),
        (
            overview.get("earnings_date_label") or "Earnings date",
            overview.get("earnings_date"),
        ),
    ]
    for start in range(0, len(key_rows), 2):
        cols = st.columns(2)
        for col, (label, value) in zip(cols, key_rows[start : start + 2]):
            col.markdown(f"**{label}**<br>{format_cell(value)}", unsafe_allow_html=True)

    if overview.get("info"):
        st.markdown('<div class="section-header">Profile</div>', unsafe_allow_html=True)
        for item in overview["info"]:
            label, value = item["label"], format_cell(item["value"])
            if item.get("url"):
                st.markdown(f"**{label}:** [{value}]({item['url']})")
            else:
                st.markdown(f"**{label}:** {value}")

    if overview.get("summary"):
        st.markdown(overview["summary"])

    news = overview.get("news") or []
    st.markdown('<div class="section-header">News</div>', unsafe_allow_html=True)
    if not news:
        st.caption("No headlines available right now.")
    for item in news[:5]:
        if item.get("url"):
            st.markdown(f"[{item['title']}]({item['url']})")
        else:
            st.markdown(item.get("title") or "—")
        st.caption(
            " · ".join(
                part
                for part in (
                    format_cell(item.get("source")),
                    format_cell(item.get("ago")),
                )
                if part != "—"
            )
            or "—"
        )


# ── Financials ───────────────────────────────────────────────────────


def statement_frame(
    statement: dict[str, Any], *, show_growth: bool
) -> tuple[list[str], list[list[str]]]:
    """Return (column labels, formatted rows) for one parsed statement."""
    periods = statement.get("periods") or []
    labels = [""] + [str(period.get("label") or "—") for period in periods]
    if show_growth:
        labels.append("YoY")

    rows: list[list[str]] = []
    for entry in statement.get("rows") or []:
        values = entry.get("values") or []
        cells = [format_cell(entry.get("label") or "—")]
        cells += [format_cell(value) for value in values]
        if show_growth:
            current = values[0] if len(values) > 0 else None
            prior = values[1] if len(values) > 1 else None
            cells.append(_signed_pct(yoy_pct(current, prior)))
        rows.append(cells)
    return labels, rows


def _render_financials(store: SQLiteStore, symbol: str) -> None:
    statement = st.selectbox(
        "Statement",
        options=list(STATEMENTS),
        format_func=lambda key: STATEMENT_LABELS[key],
        key=f"fin_statement_{symbol}",
    )
    period = st.radio(
        "Period",
        options=["annual", "quarterly"],
        format_func=str.title,
        horizontal=True,
        key=f"fin_period_{symbol}",
    )
    show_growth = st.toggle("Show YoY growth", key=f"fin_growth_{symbol}")

    data, fetched_at = load_page(
        store, symbol, "financials", statement=statement, period=period
    )
    if data is None:
        st.error(f"Could not load the {period} {STATEMENT_LABELS[statement]}.")
        return

    parsed = parse_statement(data)
    labels, rows = statement_frame(parsed, show_growth=show_growth)
    st.caption(f"as of {_as_of(fetched_at)} · {len(parsed['periods'])} periods")
    st.dataframe(
        pd.DataFrame(rows, columns=labels),
        width="stretch",
        hide_index=True,
        row_height=32,
        height=min(32 * len(rows) + 40, 900),
    )


# ── Statistics / Metrics / Forecast ──────────────────────────────────


def metrics_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pick the ratio-style statistics sections for the Metrics view."""
    by_key = {section["key"]: section for section in sections}
    return [by_key[key] for key in METRICS_KEYS if key in by_key]


def _render_sections(sections: list[dict[str, Any]]) -> None:
    if not sections:
        st.info("No statistics available for this symbol.")
        return
    for section in sections:
        st.markdown(
            f'<div class="section-header">{section["title"]}</div>',
            unsafe_allow_html=True,
        )
        if section.get("text"):
            st.caption(section["text"])
        frame = pd.DataFrame(
            [
                {
                    "Metric": format_cell(item.get("title")),
                    "Value": format_cell(item.get("value")),
                }
                for item in section["items"]
            ]
        )
        st.dataframe(frame, width="stretch", hide_index=True, row_height=28)


def _render_statistics(store: SQLiteStore, symbol: str) -> None:
    data, fetched_at = load_page(store, symbol, "statistics")
    if data is None:
        st.error("Could not load statistics for this symbol.")
        return
    st.caption(f"as of {_as_of(fetched_at)}")
    _render_sections(parse_statistics(data))


def _render_metrics(store: SQLiteStore, symbol: str) -> None:
    data, fetched_at = load_page(store, symbol, "statistics")
    if data is None:
        st.error("Could not load metrics for this symbol.")
        return
    st.caption(f"as of {_as_of(fetched_at)}")
    _render_sections(metrics_sections(parse_statistics(data)))


def _render_forecast(store: SQLiteStore, symbol: str) -> None:
    data, fetched_at = load_page(store, symbol, "forecast")
    if data is None:
        st.error("Could not load the forecast for this symbol.")
        return
    forecast = parse_forecast(data)
    st.caption(f"as of {_as_of(fetched_at)}")

    targets = forecast.get("targets")
    st.markdown(
        '<div class="section-header">Price targets</div>', unsafe_allow_html=True
    )
    if targets:
        cols = st.columns(5)
        for col, key in zip(cols, ("low", "median", "average", "high", "count")):
            col.metric(key.title(), format_cell(targets.get(key)))
        if targets.get("updated"):
            st.caption(f"updated {targets['updated']}")
    else:
        st.caption("No price targets available.")

    ratings = forecast.get("current_ratings")
    st.markdown('<div class="section-header">Ratings</div>', unsafe_allow_html=True)
    if ratings:
        cols = st.columns(6)
        for col, key in zip(
            cols, ("consensus", "strongBuy", "buy", "hold", "sell", "strongSell")
        ):
            col.metric(
                key.replace("Buy", " Buy").replace("Sell", " Sell").title(),
                format_cell(ratings.get(key)),
            )
    else:
        st.caption("No analyst ratings available.")

    estimates = forecast.get("estimates") or {}
    st.markdown('<div class="section-header">Estimates</div>', unsafe_allow_html=True)
    rows = []
    for period, stats in estimates.items():
        for field, values in stats.items():
            rows.append(
                {
                    "Basis": period.title(),
                    "Metric": field,
                    "Last": format_cell(values.get("last")),
                    "This": format_cell(values.get("this")),
                    "Growth": _signed_pct(values.get("growth")),
                }
            )
    if rows:
        st.dataframe(
            pd.DataFrame(rows), width="stretch", hide_index=True, row_height=28
        )
    else:
        st.caption("No estimates available.")

    actions = forecast.get("ratings") or []
    st.markdown(
        '<div class="section-header">Analyst actions</div>', unsafe_allow_html=True
    )
    if actions:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Date": action.get("date"),
                        "Firm": action.get("firm"),
                        "Analyst": action.get("analyst"),
                        "Action": action.get("action"),
                        "Target now": format_cell(action.get("target_now")),
                        "Target before": format_cell(action.get("target_old")),
                        "Rating": format_cell(action.get("rating_new")),
                    }
                    for action in actions
                ]
            ),
            width="stretch",
            hide_index=True,
            row_height=28,
        )
    else:
        st.caption("No analyst actions available.")
