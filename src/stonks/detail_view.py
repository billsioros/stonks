"""Streamlit rendering for the per-symbol detail page.

Only the selected section is fetched and rendered. ``st.tabs`` would evaluate
every body on each rerun, which means five payload requests per interaction;
a segmented control keeps it to one.
"""

from __future__ import annotations

import html
import time
from textwrap import dedent
from typing import Any

import pandas as pd
import streamlit as st

from stonks import report_view
from stonks.detail import RANGES, STATEMENTS, cache_key, load_history, load_page
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


def format_pct(value: Any, *, signed: bool = True) -> str:
    """Format a percentage field with its suffix; anything else is a dash."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def sparkline_svg(values: list[float], *, width: int = 720, height: int = 140) -> str:
    """Inline SVG price line: flat indigo stroke over a soft area fill."""
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = high - low or 1.0
    pad = 4.0
    step = (width - 2 * pad) / (len(values) - 1)
    points = [
        (pad + index * step, height - pad - (value - low) / span * (height - 2 * pad))
        for index, value in enumerate(values)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"{pad:.1f},{height - pad:.1f} {line} {width - pad:.1f},{height - pad:.1f}"
    return (
        f'<svg class="sk-spark" viewBox="0 0 {width} {height}" '
        'preserveAspectRatio="none" role="img" aria-label="Price history">'
        f'<polygon points="{area}" fill="rgba(99, 102, 241, 0.12)" />'
        f'<polyline points="{line}" fill="none" stroke="#6366f1" stroke-width="2" '
        'stroke-linejoin="round" stroke-linecap="round" /></svg>'
    )


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

    name = row.get("description") or symbol
    _html(
        f'<div class="sk-page-head">'
        f'<span class="sk-page-ticker">{_esc(symbol)}</span>'
        f'<span class="sk-page-name">{_esc(name)}</span>'
        f"</div>"
    )
    stamp_col, refresh_col = st.columns([4, 1])
    with stamp_col:
        st.caption(f"as of {_as_of(fetched_at)} · source StockAnalysis.com")
    with refresh_col:
        if st.button("🔄 Refresh", key=f"detail_refresh_{symbol}"):
            _clear_cache(store, symbol)
            st.rerun()

    report_view.render_symbol_report(store, symbol)

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


def _esc(value: Any) -> str:
    """Escape provider text for the HTML cards; missing values keep the dash."""
    return html.escape(str(value), quote=True)


def _html(markup: str) -> None:
    """Render a card as real HTML.

    ``st.markdown`` treats indented HTML as a code block and mangles inline
    SVG, which is why the cards go through ``st.html`` instead.
    """
    st.html(dedent(markup).strip())


def _move_class(value: Any) -> str:
    """Colour a percentage pill by sign, leaving non-numbers neutral."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return ""


def _render_quote_card(
    store: SQLiteStore, symbol: str, overview: dict[str, Any], row: dict[str, Any]
) -> None:
    """Hero surface: last price, multiples, 52-week slider and a price line."""
    price = row.get("price")
    low, high = row.get("week_52_low"), row.get("week_52_high")
    position = range_position(price, low, high)

    meta_parts = []
    if overview.get("market_cap") is not None:
        meta_parts.append(f"Market cap {_esc(format_cell(overview['market_cap']))}")
    if overview.get("pe_ratio") is not None:
        meta_parts.append(f"P/E {_esc(format_cell(overview['pe_ratio']))}")
    if overview.get("forward_pe") is not None:
        meta_parts.append(f"Forward P/E {_esc(format_cell(overview['forward_pe']))}")
    meta_html = "<br>".join(meta_parts) if meta_parts else "—"

    range_html = ""
    if low is not None and high is not None:
        pct = 0.0 if position is None else position * 100
        range_html = f"""
        <div class="sk-range">
            <div class="sk-range-track">
                <div class="sk-range-fill" style="width: {pct:.1f}%"></div>
                <div class="sk-range-dot" style="left: {pct:.1f}%"></div>
            </div>
            <div class="sk-range-labels">
                <span>52w low {_esc(format_cell(low))}</span>
                <span>{pct:.0f}% of range</span>
                <span>52w high {_esc(format_cell(high))}</span>
            </div>
        </div>"""

    _html(
        f"""<div class="sk-symbol">
            <div class="sk-symbol-head">
                <div>
                    <div class="sk-quote-label">Last price</div>
                    <div class="sk-price">{_esc(format_cell(price))}</div>
                </div>
                <div class="sk-quote-meta">{meta_html}</div>
            </div>
            {range_html}
        </div>"""
    )


def _render_price_history(store: SQLiteStore, symbol: str) -> None:
    """Price line card with a 1M / 6M / 1Y range switch."""
    state_key = f"detail_chart_span_{symbol}"
    with st.container(key="detail-chart"):
        title_col, range_col = st.columns([3, 2], vertical_alignment="center")
        with title_col:
            _html('<div class="sk-card-title">Price history</div>')
        with range_col:
            span = st.segmented_control(
                "Range",
                options=list(RANGES),
                default=st.session_state.get(state_key, "1Y"),
                key=state_key,
                label_visibility="collapsed",
            )

        history = load_history(store, symbol, span or "1Y")
        closes = [point["close"] for point in history]
        if len(closes) < 2 or not closes[0]:
            st.caption("No price history available for this range.")
            return

        change = (closes[-1] / closes[0] - 1) * 100
        trend = "up" if change > 0 else "down" if change < 0 else ""
        _html(
            f'<div class="sk-chart">{sparkline_svg(closes)}</div>'
            f'<div class="sk-range-labels">'
            f"<span>{_esc(history[0]['date'])}</span>"
            f'<span class="sk-chart-change {trend}">{change:+.1f}%</span>'
            f"<span>{_esc(history[-1]['date'])}</span>"
            f"</div>"
        )


def _render_pills(items: list[tuple[str, str, Any]]) -> None:
    """A row of small labelled tiles; `raw` decides the colour of the value."""
    cells = "".join(
        f'<div class="sk-pill"><span class="sk-pill-label">{_esc(label)}</span>'
        f'<span class="sk-pill-value {_move_class(raw)}">{_esc(value)}</span></div>'
        for label, value, raw in items
    )
    _html(f'<div class="sk-pills">{cells}</div>')


def _render_cells(items: list[tuple[str, str]]) -> None:
    """A single card made of label/value rows, two per row on wide screens."""
    cells = "".join(
        f'<div class="sk-cell"><span class="sk-cell-label">{_esc(label)}</span>'
        f'<span class="sk-cell-value">{_esc(value)}</span></div>'
        for label, value in items
    )
    _html(f'<div class="sk-grid">{cells}</div>')


def _render_profile_card(info: list[dict[str, Any]]) -> None:
    rows = "".join(
        f'<div class="sk-kv"><span class="sk-kv-label">{_esc(item.get("label"))}</span>'
        f'<span class="sk-kv-value">{_link_or_text(item)}</span></div>'
        for item in info
    )
    _html(f'<div class="sk-card">{rows}</div>')


def _link_or_text(item: dict[str, Any]) -> str:
    value = _esc(format_cell(item.get("value")))
    url = item.get("url")
    if not url:
        return value
    return (
        f'<a href="{html.escape(str(url), quote=True)}" target="_blank" '
        f'rel="noopener" style="color: var(--accent-primary);">{value}</a>'
    )


def _render_news(items: list[dict[str, Any]]) -> None:
    blocks = []
    for item in items[:5]:
        title = _esc(item.get("title") or "Untitled")
        meta = " · ".join(
            _esc(part)
            for part in (
                format_cell(item.get("source")),
                format_cell(item.get("ago")),
            )
            if part != "—"
        )
        body = (
            f'<div class="sk-news-title">{title}</div>'
            f'<div class="sk-news-meta">{meta or "—"}</div>'
        )
        url = item.get("url")
        if url:
            blocks.append(
                f'<a class="sk-news-item" href="{html.escape(str(url), quote=True)}"'
                f' target="_blank" rel="noopener">{body}</a>'
            )
        else:
            blocks.append(f'<div class="sk-news-item">{body}</div>')
    _html(f'<div class="sk-news">{"".join(blocks)}</div>')


def _render_overview(
    store: SQLiteStore,
    symbol: str,
    overview: dict[str, Any],
    row: dict[str, Any],
) -> None:
    _render_quote_card(store, symbol, overview, row)
    _render_price_history(store, symbol)

    _render_pills(
        [
            ("Analyst rating", format_cell(row.get("rating")), None),
            (
                "Target upside",
                format_pct(row.get("pt_upside_pct")),
                row.get("pt_upside_pct"),
            ),
            (
                "DCF upside",
                format_pct(row.get("dcf_upside_pct")),
                row.get("dcf_upside_pct"),
            ),
            (
                "Lynch upside",
                format_pct(row.get("lynch_upside_pct")),
                row.get("lynch_upside_pct"),
            ),
            ("Short float", format_pct(row.get("short_pct"), signed=False), None),
            ("Forward P/E", format_cell(overview.get("forward_pe")), None),
        ]
    )

    _render_cells(
        [
            ("Revenue (TTM)", format_cell(overview.get("revenue"))),
            ("Revenue growth", format_cell(overview.get("revenue_growth"))),
            ("Net income (TTM)", format_cell(overview.get("net_income"))),
            ("Net income growth", format_cell(overview.get("net_income_growth"))),
            ("EPS (TTM)", format_cell(overview.get("eps"))),
            ("P/E", format_cell(overview.get("pe_ratio"))),
            ("Shares out", format_cell(overview.get("shares_out"))),
            ("Beta", format_cell(overview.get("beta"))),
            ("Dividend", format_cell(overview.get("dividend"))),
            (
                overview.get("earnings_date_label") or "Earnings date",
                format_cell(overview.get("earnings_date")),
            ),
        ]
    )

    if overview.get("info"):
        st.markdown('<div class="section-header">Profile</div>', unsafe_allow_html=True)
        _render_profile_card(overview["info"])

    if overview.get("summary"):
        _html(f'<div class="sk-card"><p>{_esc(overview["summary"])}</p></div>')

    news = overview.get("news") or []
    st.markdown('<div class="section-header">News</div>', unsafe_allow_html=True)
    if news:
        _render_news(news)
    else:
        st.caption("No headlines available right now.")


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
    period_col, growth_col = st.columns([2, 1])
    with period_col:
        period = st.radio(
            "Period",
            options=["annual", "quarterly"],
            format_func=str.title,
            horizontal=True,
            key=f"fin_period_{symbol}",
        )
    with growth_col:
        show_growth = st.toggle("Show YoY growth", key=f"fin_growth_{symbol}")

    data, fetched_at = load_page(
        store, symbol, "financials", statement=statement, period=period
    )
    if data is None:
        st.error(f"Could not load the {period} {STATEMENT_LABELS[statement]}.")
        return

    parsed = parse_statement(data)
    labels, rows = statement_frame(parsed, show_growth=show_growth)
    st.markdown(
        f'<div class="sk-card-title">{_esc(STATEMENT_LABELS[statement])} · '
        f"{_esc(str(period).title())}</div>",
        unsafe_allow_html=True,
    )
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


def _render_card(title: str, rows: str, *, text: str | None = None) -> None:
    """One titled card holding label/value rows."""
    caption = f'<p class="sk-card-text">{_esc(text)}</p>' if text else ""
    _html(
        f'<div class="sk-card"><div class="sk-card-title">{_esc(title)}</div>'
        f"{caption}{rows}</div>"
    )


def _render_sections(sections: list[dict[str, Any]]) -> None:
    """Statistics and metrics as a two-column grid of cards, not wide tables."""
    if not sections:
        st.info("No statistics available for this symbol.")
        return
    for start in range(0, len(sections), 2):
        pair = sections[start : start + 2]
        cols = st.columns(len(pair))
        for col, section in zip(cols, pair):
            rows = "".join(
                f'<div class="sk-kv"><span class="sk-kv-label">'
                f"{_esc(format_cell(item.get('title')))}</span>"
                f'<span class="sk-kv-value">{_esc(format_cell(item.get("value")))}'
                "</span></div>"
                for item in section["items"]
            )
            with col:
                _render_card(section["title"], rows, text=section.get("text"))


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


def _estimate_rows(forecast: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the per-period estimate stats into table rows."""
    rows = []
    for period, stats in (forecast.get("estimates") or {}).items():
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
    return rows


def _render_forecast(store: SQLiteStore, symbol: str) -> None:
    data, fetched_at = load_page(store, symbol, "forecast")
    if data is None:
        st.info(f"StockAnalysis has no forecast data for {symbol}.")
        return

    forecast = parse_forecast(data)
    targets = forecast.get("targets")
    ratings = forecast.get("current_ratings")
    rows = _estimate_rows(forecast)
    actions = forecast.get("ratings") or []

    # Covered and uncovered symbols both land here; only say it once.
    if not targets and not ratings and not rows and not actions:
        st.info(f"StockAnalysis has no analyst coverage for {symbol}.")
        return

    st.caption(f"as of {_as_of(fetched_at)}")

    if targets:
        st.markdown(
            '<div class="section-header">Price targets</div>', unsafe_allow_html=True
        )
        _render_pills(
            [
                (label, format_cell(targets.get(key)), None)
                for label, key in (
                    ("Low", "low"),
                    ("Median", "median"),
                    ("Average", "average"),
                    ("High", "high"),
                    ("Analysts", "count"),
                )
            ]
        )
        if targets.get("updated"):
            st.caption(f"updated {targets['updated']}")

    if ratings:
        st.markdown('<div class="section-header">Ratings</div>', unsafe_allow_html=True)
        _render_pills(
            [
                (label, format_cell(ratings.get(key)), None)
                for label, key in (
                    ("Consensus", "consensus"),
                    ("Strong buy", "strongBuy"),
                    ("Buy", "buy"),
                    ("Hold", "hold"),
                    ("Sell", "sell"),
                    ("Strong sell", "strongSell"),
                )
            ]
        )

    if rows:
        st.markdown(
            '<div class="section-header">Estimates</div>', unsafe_allow_html=True
        )
        st.dataframe(
            pd.DataFrame(rows), width="stretch", hide_index=True, row_height=28
        )

    if actions:
        st.markdown(
            '<div class="section-header">Analyst actions</div>',
            unsafe_allow_html=True,
        )
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
