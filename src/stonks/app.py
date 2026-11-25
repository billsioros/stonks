"""Stonks — Streamlit Stock Screener App.

Run with: streamlit run src/stonks/app.py
"""

import logging
import math
import re
import time
from collections.abc import Sequence
from datetime import datetime
from html import escape as _escape
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import streamlit as st

from stonks import config, report, report_view, sanity
from stonks.backtest_view import (
    _RESULT_KEY,
    _SETTINGS_KEY,
    holdings_settings_from_summary,
    render_backtest_tab,
    run_configured_backtest,
)
from stonks.config import (
    COLUMN_DISPLAY_NAMES,
    COLUMN_HELP,
    DEFAULT_PAGE_SIZE,
    ENUM_FILTER_COLUMNS,
    NUMERIC_FILTER_COLUMNS,
    PAGE_SIZE_OPTIONS,
    SCREENER_TABLE_MAX_HEIGHT,
    VIEW_PRESETS,
)
from stonks.correlation import portfolio_correlation_factor
from stonks.detail_view import render_detail_page
from stonks.portfolio import (
    CONVERTIBLE_CURRENCIES,
    backtest_allocation,
    portfolio_snapshot,
    validate_lot,
)
from stonks.presets import POPULAR_SCREENS, default_screen
from stonks.store import SQLiteStore, is_stock_row

logger = logging.getLogger(__name__)

# ── Page configuration ──────────────────────────────────────────────
st.set_page_config(
    page_title="Stonks",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ──────────────────────────────────────────────────────
st.markdown(
    """
<style>
/* Flat dark theme, mirroring the roomies dashboard: navy surfaces, hairline
   borders, no gradients or glow. Indigo stays the primary accent, and these
   selectors track Streamlit's rendered DOM, so re-check them on upgrades. */
:root {
    --bg-primary: #0b0f19;
    --bg-secondary: #0f172a;
    --bg-card: #1e293b;
    --accent-primary: #6366f1;
    --accent-soft: rgba(99, 102, 241, 0.12);
    --accent-border: rgba(99, 102, 241, 0.5);
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --border-color: rgba(255, 255, 255, 0.08);
    --success: #10b981;
    --danger: #ef4444;
    --warning: #f59e0b;
}

html, body, [class*="css"], .stMarkdown, .stText, p, span, li, label, div {
    color: var(--text-primary);
}

.stApp {
    background: var(--bg-primary) !important;
}

[data-testid="stHeader"] {
    background: transparent !important;
}

.main .block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 3.5rem !important;
    max-width: 100% !important;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: var(--bg-secondary) !important;
    border-right: 1px solid var(--border-color) !important;
}

section[data-testid="stSidebar"] .block-container {
    padding-top: 1rem !important;
    padding-bottom: 3.5rem !important;
}

/* Headings */
h1, h2, h3 { color: var(--text-primary) !important; font-weight: 600 !important; }
h2 { border-bottom: 1px solid var(--border-color); padding-bottom: 8px; }

/* Masthead */
.sk-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1.5rem;
    flex-wrap: wrap;
    padding: 0 0 1.5rem;
    margin-bottom: 1.8rem;
    border-bottom: 1px solid var(--border-color);
}

.sk-brand {
    display: flex;
    align-items: center;
    gap: 1.1rem;
}

.sk-mark {
    width: 56px;
    height: 56px;
    flex: none;
    display: grid;
    place-items: center;
    border-radius: 14px;
    overflow: hidden;
    font-size: 2.6rem;
    line-height: 1;
}

.sk-brand h1 {
    font-weight: 700;
    font-size: clamp(2.2rem, 4vw, 3rem);
    letter-spacing: -0.03em;
    line-height: 1;
    margin: 0 !important;
    padding: 0 !important;
    color: var(--text-primary);
}

.sk-meta {
    text-align: right;
}

.sk-meta p {
    margin: 0;
    color: var(--text-secondary);
    font-size: 0.85rem;
}

.sk-badges {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-top: 0.5rem;
}

.sk-badge {
    font-size: 0.72rem;
    font-weight: 600;
    padding: 2px 10px;
    border-radius: 999px;
    border: 1px solid currentColor;
    white-space: nowrap;
}

.sk-badge-ok { color: #22c55e; }
.sk-badge-fail { color: #ef4444; }
.sk-badge-unknown { color: #94a3b8; }

/* Sidebar section label, matching the masthead's quieter register */
.sk-side-title {
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--text-primary);
    padding: 0 0 0.9rem;
}

/* Screens and watchlist entries: roomies' card surface, sized for a sidebar */
[class*="st-key-screen-"] {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 0.85rem 0.9rem;
    margin-bottom: 0.6rem;
    transition: border-color 0.15s ease;
}

[class*="st-key-screen-"]:hover {
    border-color: var(--accent-border);
}

[class*="st-key-screen-"] .stButton > button {
    background: transparent;
    min-height: 2rem;
    padding: 0 0.5rem;
}

/* Sidebar cards are narrower than the main column: tighter padding, no
   wrapping action buttons, and text that can shrink without overflowing. */
[data-testid="stSidebar"] [class*="st-key-screen-"] {
    padding: 0.55rem 0.65rem;
    margin-bottom: 0.45rem;
}

[data-testid="stSidebar"] [class*="st-key-screen-"] [data-testid="stHorizontalBlock"] {
    gap: 0.35rem;
    align-items: center;
    flex-wrap: nowrap;
}

[data-testid="stSidebar"] [class*="st-key-screen-"] [data-testid="stMarkdownContainer"] p {
    margin: 0;
    font-size: 0.82rem;
}

[data-testid="stSidebar"] [class*="st-key-screen-"] [data-testid="stCaptionContainer"] {
    font-size: 0.72rem;
    line-height: 1.25;
}

[data-testid="stSidebar"] [class*="st-key-screen-"] .stButton > button {
    min-width: 2.75rem;
    width: 2.75rem;
    flex: 0 0 2.75rem;
    min-height: 2.25rem;
    padding: 0;
    white-space: nowrap;
}

/* Metric cards: flat surfaces with high-contrast values, no glow */
[data-testid="stMetric"] {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 16px;
    transition: border-color 0.2s ease;
}

[data-testid="stMetric"]:hover {
    border-color: var(--accent-border);
}

[data-testid="stMetricValue"] {
    color: var(--text-primary) !important;
    font-weight: 500;
    font-size: 2rem;
    letter-spacing: -0.01em;
    font-variant-numeric: lining-nums tabular-nums;
}

[data-testid="stMetricLabel"] {
    color: var(--text-secondary) !important;
    font-size: 0.85rem;
    font-weight: 500;
}

[data-testid="stMetricDelta"] {
    background: rgba(248, 250, 252, 0.06) !important;
    border-radius: 999px;
    padding: 0.25rem 0.75rem;
    font-size: 0.85rem;
    font-weight: 600;
}

/* Section headers */
.section-header {
    color: var(--text-primary);
    font-size: 1.1rem;
    font-weight: 600;
    margin-bottom: 0.75rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

/* Backtest: labelled sections inside the same surfaces */
.bt-section {
    color: var(--text-secondary);
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin: 0.2rem 0 0.7rem;
}

/* Alerts banner: a card above the screener, hidden entirely when empty */
[class*="st-key-alerts-banner"] {
    background: var(--bg-card);
    border: 1px solid var(--accent-border);
    border-radius: 12px;
    padding: 0.9rem 1rem 0.4rem;
    margin-bottom: 1.2rem;
}

/* Symbol detail page: roomies surfaces — flat cards, hairline borders, tabular
   numbers, indigo only where it marks something. */
.sk-page-head {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin-bottom: 0.35rem;
}

.sk-page-ticker {
    color: var(--text-primary);
    font-size: 1.6rem;
    font-weight: 700;
    letter-spacing: -0.02em;
}

.sk-page-name {
    color: var(--text-secondary);
    font-size: 0.95rem;
    font-weight: 500;
}
.sk-symbol {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 14px;
    padding: 1.3rem 1.4rem;
    margin-bottom: 1.3rem;
}

.sk-symbol-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1.5rem;
    flex-wrap: wrap;
}

.sk-quote-label {
    color: var(--text-muted);
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
}

.sk-price {
    color: var(--text-primary);
    font-size: 2.1rem;
    font-weight: 600;
    line-height: 1.15;
    font-variant-numeric: tabular-nums;
}

.sk-quote-meta {
    color: var(--text-secondary);
    font-size: 0.8rem;
    text-align: right;
    line-height: 1.7;
}

.sk-range {
    margin-top: 1.2rem;
}

.sk-range-track {
    position: relative;
    height: 6px;
    border-radius: 999px;
    background: rgba(248, 250, 252, 0.07);
}

.sk-range-fill {
    position: absolute;
    inset: 0 auto 0 0;
    border-radius: 999px;
    background: var(--accent-primary);
    opacity: 0.85;
}

.sk-range-dot {
    position: absolute;
    top: 50%;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--text-primary);
    border: 2px solid var(--accent-primary);
    transform: translate(-50%, -50%);
}

.sk-range-labels {
    display: flex;
    justify-content: space-between;
    color: var(--text-muted);
    font-size: 0.75rem;
    margin-top: 0.5rem;
    font-variant-numeric: tabular-nums;
}

.sk-pills {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
    gap: 0.6rem;
    margin-bottom: 1.3rem;
}

.sk-pill {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 0.7rem 0.85rem;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
}

.sk-pill-label {
    color: var(--text-muted);
    font-size: 0.66rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
}

.sk-pill-value {
    color: var(--text-primary);
    font-size: 1rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
}

.sk-pill-value.up { color: var(--success); }
.sk-pill-value.down { color: var(--danger); }

.sk-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 1.3rem;
}

.sk-cell {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 1rem;
    padding: 0.7rem 1rem;
    border-bottom: 1px solid rgba(248, 250, 252, 0.05);
}

.sk-cell-label {
    color: var(--text-muted);
    font-size: 0.78rem;
}

.sk-cell-value {
    color: var(--text-primary);
    font-weight: 600;
    font-size: 0.88rem;
    font-variant-numeric: tabular-nums;
}

.sk-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 0.95rem 1.15rem;
    margin-bottom: 1.3rem;
}

.sk-card p {
    margin: 0;
    color: var(--text-secondary);
    font-size: 0.9rem;
    line-height: 1.65;
}

.sk-card-title {
    color: var(--text-muted);
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-bottom: 0.6rem;
}

.sk-card-text {
    margin: 0 0 0.5rem !important;
    color: var(--text-muted) !important;
    font-size: 0.78rem !important;
}

.sk-chart-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 1.2rem;
}

.sk-chart {
    height: 140px;
    margin-top: 0.5rem;
}

.sk-chart svg {
    display: block;
    width: 100%;
    height: 100%;
}

.sk-chart-change {
    font-size: 0.95rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--text-secondary);
}

.sk-chart-change.up { color: var(--success); }
.sk-chart-change.down { color: var(--danger); }

.sk-kv {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.42rem 0;
    font-size: 0.85rem;
    border-bottom: 1px solid rgba(248, 250, 252, 0.05);
}

.sk-kv:last-child { border-bottom: none; }
.sk-kv-label { color: var(--text-muted); }
.sk-kv-value { color: var(--text-primary); font-weight: 500; text-align: right; }

.sk-news {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin-bottom: 1.3rem;
}

.sk-news-item {
    display: block;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 0.75rem 0.95rem;
    text-decoration: none !important;
    transition: border-color 0.15s ease;
}

.sk-news-item:hover { border-color: var(--accent-border); }

.sk-news-title {
    color: var(--text-primary);
    font-size: 0.9rem;
    font-weight: 500;
    line-height: 1.4;
}

.sk-news-meta {
    color: var(--text-muted);
    font-size: 0.75rem;
    margin-top: 0.3rem;
}

/* Pagination */
.pagination-info {
    color: var(--text-secondary);
    font-size: 0.85rem;
    text-align: center;
    padding: 0.5rem;
}

/* Buttons: card surface, border only */
.stButton > button {
    background: var(--bg-card);
    color: var(--text-primary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    font-weight: 500;
    transition: border-color 0.15s, background 0.15s, color 0.15s;
}

.stButton > button:hover {
    border-color: var(--accent-primary);
    background: var(--accent-soft);
    color: var(--accent-primary);
}

.stDownloadButton > button {
    border-radius: 8px !important;
    font-weight: 500 !important;
}

:focus-visible {
    outline: 2px solid var(--accent-primary) !important;
    outline-offset: 2px;
}

/* Data editor/table: roomies' card surface around the grid */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border-color);
    border-radius: 12px;
    overflow: hidden;
    background: var(--bg-card);
}

/* Tabs: text only, underline marks active */
.stTabs [data-baseweb="tab-list"] {
    gap: 1.6rem;
    border-bottom: 1px solid var(--border-color);
}

.stTabs [data-baseweb="tab"] {
    background: none;
    padding: 0.6rem 0;
    height: auto;
    color: var(--text-secondary);
    font-weight: 500;
}

.stTabs [aria-selected="true"] {
    color: var(--text-primary);
}

[data-baseweb="tab-highlight"] {
    background: var(--accent-primary);
    height: 2px;
}

[data-baseweb="tab-border"] {
    display: none;
}

/* Alerts */
[data-testid="stAlert"] {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    color: var(--text-primary);
}

/* Inputs */
.stTextInput > div > div,
.stTextInput div[data-baseweb="input"],
.stDateInput > div > div,
.stSelectbox div[data-baseweb="select"] > div,
.stMultiSelect div[data-baseweb="select"] > div {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 8px;
}

.stTextInput > div > div:focus-within,
.stTextInput div[data-baseweb="input"]:focus-within {
    border-color: var(--accent-primary);
    box-shadow: 0 0 0 2px var(--accent-soft);
}

/* Sliders */
.stSlider [data-baseweb="slider"] {
    color: var(--accent-primary);
}

/* Expander: a card like every other surface, not a tinted strip */
[data-testid="stExpander"] details {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
}

.streamlit-expanderHeader,
[data-testid="stExpander"] summary {
    font-weight: 600 !important;
    font-size: 0.95rem !important;
    background: transparent !important;
    border-radius: 12px !important;
}

/* Footer: pinned to the viewport, with content padded so it never overlaps */
.app-footer {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 100;
    text-align: center;
    color: var(--text-muted);
    font-size: 0.75rem;
    padding: 0.55rem 1.25rem;
    background: var(--bg-primary);
    border-top: 1px solid var(--border-color);
    margin: 0;
}

/* Scrollbar */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: var(--bg-primary);
}

::-webkit-scrollbar-thumb {
    background: #334155;
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--text-muted);
}

/* Plotly chart containers */
.js-plotly-plot .plotly .main-svg {
    background: transparent !important;
}

/* Hide default Streamlit footer */
footer {
    display: none;
}
</style>
""",
    unsafe_allow_html=True,
)


# ── Initialize services (cached) ────────────────────────────────────
@st.cache_resource
def get_store() -> SQLiteStore:
    return SQLiteStore()


def open_symbol(symbol: str) -> None:
    """Switch the app to the detail page for `symbol`."""
    st.session_state["detail_symbol"] = symbol
    st.session_state["page"] = "detail"


def close_detail() -> None:
    """Return to the screener, leaving its filters and paging untouched."""
    st.session_state["page"] = "screener"
    # Streamlit keeps a dataframe's selection under its widget key, which cannot
    # be cleared directly; a new epoch gives both tables fresh keys instead.
    st.session_state["selection_epoch"] = st.session_state.get("selection_epoch", 0) + 1


def _table_key(name: str) -> str:
    """Widget key for a selectable table, versioned so Back clears selection."""
    return f"{name}_{st.session_state.get('selection_epoch', 0)}"


def _is_missing(val: object) -> bool:
    """True for None or NaN (pandas turns NULLs into NaN in the display frame)."""
    return val is None or (isinstance(val, float) and math.isnan(val))


def _fmt_flag(val: object) -> str:
    """Render the 13F flag, keeping explicit zero distinct from missing data."""
    if _is_missing(val):
        return "—"
    return "🐋" if val else "✗"


def _fmt_upside(val: float | None) -> str:
    """Render an upside with its direction: green for gains, red for losses."""
    if _is_missing(val) or val is None:
        return "—"
    return f"{'🟢' if val >= 0 else '🔴'} {val:+.1f}%"


def _fmt_current_ratio(val: float | None) -> str:
    """Render the current ratio, marking liquidity below 1."""
    if _is_missing(val) or val is None:
        return "—"
    return f"🔴 {val:.2f}" if val < 1.0 else f"{val:.2f}"


def _fmt_market_cap(val: float | None) -> str:
    """Format market cap in human-readable form."""
    if _is_missing(val) or val is None:
        return "—"
    if val >= 1_000_000:
        return f"{val / 1_000_000:.2f}T"
    if val >= 1_000:
        return f"{val / 1_000:.2f}B"
    return f"{val:.2f}M"


def _fmt_pct(val: float | None) -> str:
    """Format a percentage value."""
    if _is_missing(val):
        return "—"
    return f"{val:.2f}%"


def _fmt_number(val: float | None, decimals: int = 2) -> str:
    """Format a generic number."""
    if _is_missing(val):
        return "—"
    return f"{val:,.{decimals}f}"


def _money(val: float | None, currency: str) -> str:
    """Format an amount in its own currency, or a dash when unavailable."""
    return "—" if val is None or _is_missing(val) else f"{val:,.2f} {currency}"


def _signed_money(val: float | None) -> str:
    """Format a USD gain or loss with an explicit sign."""
    if val is None or _is_missing(val):
        return "—"
    return f"{'-' if val < 0 else '+'}${abs(val):,.2f}"


def _fmt_cyclical_risk(val: object) -> str:
    """Render the cyclical peak flag as a warning badge."""
    if _is_missing(val) or val is None:
        return "—"
    return "⚠️ Peak" if val else ""


def _format_display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a formatted copy; sorting and filtering stay on the raw values."""
    display = frame.copy()
    for col in display.columns:
        if col == "13F Whale":
            display[col] = display[col].apply(_fmt_flag)
        elif col == "Cyclical Peak Risk":
            display[col] = display[col].apply(_fmt_cyclical_risk)
        elif col == "Market Cap":
            display[col] = display[col].apply(_fmt_market_cap)
        elif col in ("PT Upside", "DCF Upside %", "Lynch Upside %", "Avg Upside %"):
            display[col] = display[col].apply(_fmt_upside)
        elif col == "Current Ratio":
            display[col] = display[col].apply(_fmt_current_ratio)
        elif "%" in col or "Upside" in col or "Short" in col:
            display[col] = display[col].apply(_fmt_pct)
        elif col in (
            "P/E",
            "PE Ratio",
            "P/B",
            "P/S",
            "PEG",
            "EV/EBITDA",
            "EV/EBITDA^",
            "Beta",
            "DCF Fair Value",
            "Lynch Fair Value",
        ):
            display[col] = display[col].apply(lambda x: _fmt_number(x, 2))
    return display


def _prune_filters(filters: dict[str, Any]) -> dict[str, Any]:
    """Drop filter entries that cannot constrain anything."""
    pruned: dict[str, Any] = {}
    for col, spec in filters.items():
        if not isinstance(spec, dict):
            continue
        cleaned = {key: value for key, value in spec.items() if value is not None}
        if not cleaned:
            continue
        if "values" in cleaned and not cleaned["values"]:
            continue
        pruned[col] = cleaned
    return pruned


def apply_screen_state(screen: dict[str, Any]) -> None:
    """Load a screen's filters, view and sorting into the session, consistently."""
    st.session_state["active_filters"] = _prune_filters(screen.get("filters") or {})
    st.session_state["view_preset"] = screen.get("view_preset", "Overview")
    if screen.get("sort_column"):
        st.session_state["sort_column"] = screen["sort_column"]
    st.session_state["sort_ascending"] = screen.get("sort_ascending", True)
    st.session_state["current_page"] = 1


def _next_attempt_text(raw: Any, *, now: float) -> str:
    """Describe the recorded next attempt, tolerating missing or bad metadata."""
    try:
        when = float(raw)
    except (TypeError, ValueError):
        return ""
    remaining = min(when - now, config.WORKER_INTERVAL_MINUTES * 60)
    if remaining <= 0:
        return " Next attempt due now."
    if remaining < 60:
        return " Next attempt in <1m."
    return f" Next attempt in {int(remaining // 60)}m."


def live_sync_state(
    sync_info: dict[str, Any], *, now: float | None = None
) -> sanity.Badge:
    """Judge the worker from its last recorded attempt, not from a constant."""
    moment = now if now is not None else time.time()
    next_text = _next_attempt_text(sync_info.get("next_sync_at"), now=moment)
    if sync_info.get("last_sync_status") == "failed":
        return sanity.Badge(
            "fail", "Live Sync", f"Last sync attempt failed.{next_text}"
        )

    success_at = sync_info.get("last_successful_sync_at")
    if not success_at:
        return sanity.Badge(
            "unknown", "Live Sync", f"No successful sync recorded.{next_text}"
        )
    try:
        age = max(0.0, moment - float(success_at))
    except (TypeError, ValueError):
        return sanity.Badge(
            "unknown", "Live Sync", f"Unreadable sync timestamp.{next_text}"
        )

    if age < 3600:
        age_text = f"{int(age // 60)}m ago"
    else:
        age_text = f"{int(age // 3600)}h {int((age % 3600) // 60)}m ago"
    detail = f"Last successful sync {age_text}."
    if age > config.SYNC_ACTIVE_WINDOW_MINUTES * 60:
        return sanity.Badge(
            "fail",
            "Live Sync",
            f"{detail} Outside the active sync window.{next_text}",
        )
    return sanity.Badge("ok", "Live Sync", f"{detail}{next_text}")


def render_header(store: SQLiteStore) -> None:
    """Render the masthead: brand on the left, evidence-backed badges on the right."""
    sync_info = store.get_last_sync_info()
    sync_info["last_sync_status"] = store.get_metadata("last_sync_status")
    sync_info["last_successful_sync_at"] = store.get_metadata("last_successful_sync_at")
    sync_info["last_sync_error"] = store.get_metadata("last_sync_error")
    sync_info["next_sync_at"] = store.get_metadata("next_sync_at")
    badges = (
        live_sync_state(sync_info),
        sanity.compatibility(sanity.load_report(store)),
    )
    pills = "".join(
        f'<span class="sk-badge sk-badge-{badge.level}" title="{_escape(badge.detail)}">'
        f"{_escape(badge.label)}</span>"
        for badge in badges
    )
    st.markdown(
        f"""
    <div class="sk-head">
        <div class="sk-brand">
            <div class="sk-mark">📈</div>
            <h1>Stonks</h1>
        </div>
        <div class="sk-meta">
            <div class="sk-badges">{pills}</div>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def _slug(text: str) -> str:
    """Turn a screen name into a CSS-safe key fragment."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _describe_screen(screen: dict[str, Any]) -> str:
    """One-line summary of a saved screen's shape."""
    parts = [f"{screen.get('view_preset') or 'Overview'} view"]
    filters = screen.get("filters") or {}
    parts.append(f"{len(filters)} filters" if filters else "no filters")
    if screen.get("sort_column"):
        display = COLUMN_DISPLAY_NAMES.get(screen["sort_column"], screen["sort_column"])
        direction = "desc" if not screen.get("sort_ascending", True) else "asc"
        parts.append(f"sorted by {display} ({direction})")
    return " · ".join(parts)


def _screen_column_ratios(_allow_delete: bool) -> list[int]:
    """Reserve two square action slots in every screen card so titles align."""
    return [3, 1, 1]


def _screen_card(
    key: str,
    title: str,
    description: str | None,
    *,
    allow_delete: bool = False,
) -> tuple[bool, bool]:
    """Render one screen as a card and return (load_clicked, delete_clicked)."""
    with st.container(key=f"screen-{key}"):
        cols = st.columns(_screen_column_ratios(allow_delete))
        with cols[0]:
            st.markdown(f"**{title}**")
            if description:
                st.caption(description)
        with cols[1]:
            load = st.button("▶", key=f"load_screen_{key}", help="Load this screen")
        delete = False
        if allow_delete:
            with cols[2]:
                delete = st.button("🗑", key=f"del_screen_{key}", help="Delete")
    return load, delete


def render_sidebar_filters() -> dict[str, Any]:
    """Render the sidebar filter builder without requiring df."""
    with st.sidebar:
        # ── Section label ────────────────────────────────────────
        st.markdown(
            '<div class="sk-side-title">🧭 Screens</div>', unsafe_allow_html=True
        )

        # ── Popular Screens ──────────────────────────────────────
        with st.expander("🌟 Popular Screens", expanded=False):
            for preset in POPULAR_SCREENS:
                load, _ = _screen_card(
                    f"popular-{_slug(preset['name'])}",
                    preset["name"],
                    preset["description"],
                )
                if load:
                    apply_screen_state(preset)
                    st.rerun()

        # ── Saved Screens ────────────────────────────────────────
        store = get_store()
        with st.expander("💾 Saved Screens", expanded=False):
            for screen in store.list_screens():
                load, delete = _screen_card(
                    f"saved-{_slug(screen['name'])}",
                    screen["name"],
                    _describe_screen(screen),
                    allow_delete=True,
                )
                if load:
                    apply_screen_state(screen)
                    st.rerun()
                if delete:
                    store.delete_screen(screen["name"])
                    st.rerun()

            # Save current filters
            st.divider()
            save_name = st.text_input(
                "Screen name", key="save_screen_name", placeholder="My Screen"
            )
            if st.button(
                "💾 Save Current Filters",
                key="save_screen_btn",
                width="stretch",
            ):
                if save_name:
                    current_filters = _prune_filters(
                        st.session_state.get("active_filters", {})
                    )
                    view_preset = st.session_state.get("view_preset", "Overview")
                    sort_col = st.session_state.get("sort_column")
                    sort_asc = st.session_state.get("sort_ascending", True)
                    store.save_screen(
                        save_name, current_filters, view_preset, sort_col, sort_asc
                    )
                    st.toast(f"✅ Screen '{save_name}' saved!", icon="💾")
                else:
                    st.warning("Please enter a name.")

    return st.session_state.get("active_filters", {})  # type: ignore[no-any-return]


def render_top_filters() -> dict[str, Any]:
    """Render numeric and category filters in a grid above the stock view."""
    filters = st.session_state.get("active_filters", {}).copy()
    store = get_store()
    available_numeric = [c for c in NUMERIC_FILTER_COLUMNS]
    available_enum = [c for c in ENUM_FILTER_COLUMNS]

    with st.expander("🎯 Filters", expanded=False):
        # ── Filter Top Bar ───────────────────────────────────────
        ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1, 2, 1])

        with ctrl_col1:
            # Dropdown to add a new filter
            filter_to_add = st.selectbox(
                "➕ Add Filter",
                options=[""]
                + [COLUMN_DISPLAY_NAMES.get(c, c) for c in available_numeric],
                key="add_filter_dropdown",
            )
            if filter_to_add:
                # Find the column key for the display name
                col_key = next(
                    (k for k, v in COLUMN_DISPLAY_NAMES.items() if v == filter_to_add),
                    filter_to_add,
                )
                if col_key not in filters:
                    filters[col_key] = {"min": None, "max": None}
                    st.session_state["active_filters"] = filters
                    st.rerun()

        with ctrl_col2:
            search_query = st.text_input(
                "🔍 Search symbols",
                value=st.session_state.get("search_query", ""),
                placeholder="Symbol or company name...",
                key="search_input_top",
            )
            st.session_state["search_query"] = search_query

        with ctrl_col3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🧹 Reset All", key="reset_filters_top", width="stretch"):
                st.session_state["active_filters"] = {}
                st.session_state["search_query"] = ""
                st.session_state["current_page"] = 1
                st.rerun()

        # ── Category Filters ──────────────────────────────────────
        col_cat1, col_cat2, col_cat3, col_cat4 = st.columns(4)
        cat_cols = [col_cat1, col_cat2, col_cat3, col_cat4]

        for i, col in enumerate(available_enum):
            unique_vals = store.get_unique_values(col)
            if not unique_vals:
                continue

            with cat_cols[i % 4]:
                selected = st.multiselect(
                    COLUMN_DISPLAY_NAMES.get(col, col),
                    options=unique_vals,
                    default=filters.get(col, {}).get("values", []),
                    key=f"top_filter_enum_{col}",
                )
                if selected:
                    filters[col] = {"values": selected}
                elif col in filters and "values" in filters[col]:
                    del filters[col]

        st.divider()

        # ── Filter Grid ──────────────────────────────────────────
        st.markdown('<div class="filter-grid">', unsafe_allow_html=True)

        # We'll use columns to simulate a grid because Streamlit doesn't support raw grid well
        active_cols = sorted([c for c in filters if c in NUMERIC_FILTER_COLUMNS])

        if active_cols:
            rows = (len(active_cols) + 2) // 3  # 3 columns
            for i in range(rows):
                cols = st.columns(3)
                for j in range(3):
                    idx = i * 3 + j
                    if idx < len(active_cols):
                        col = active_cols[idx]
                        display_name = COLUMN_DISPLAY_NAMES.get(col, col)
                        spec = filters.get(col, {})

                        with cols[j]:
                            st.markdown(f"**{display_name}**")
                            c_min, c_max, c_del = st.columns([4, 4, 1])
                            with c_min:
                                min_val = st.number_input(
                                    "Min",
                                    value=float(spec.get("min"))
                                    if spec.get("min") is not None
                                    else None,
                                    key=f"top_min_{col}",
                                    label_visibility="collapsed",
                                    placeholder="Min",
                                )
                            with c_max:
                                max_val = st.number_input(
                                    "Max",
                                    value=float(spec.get("max"))
                                    if spec.get("max") is not None
                                    else None,
                                    key=f"top_max_{col}",
                                    label_visibility="collapsed",
                                    placeholder="Max",
                                )
                            with c_del:
                                # Spacer
                                st.markdown(
                                    '<div style="height: 0.5rem"></div>',
                                    unsafe_allow_html=True,
                                )
                                if st.button(
                                    "✕",
                                    key=f"del_filter_{col}",
                                    help=f"Remove {display_name} filter",
                                ):
                                    del filters[col]
                                    st.session_state["active_filters"] = filters
                                    st.rerun()

                            # Update filters dict
                            new_spec = {}

                            if min_val is not None:
                                new_spec["min"] = min_val

                            if max_val is not None:
                                new_spec["max"] = max_val

                            # Update local filters dict; caller will sync to session state
                            filters[col] = new_spec

        st.markdown("</div>", unsafe_allow_html=True)

        # Apply button & Update session state
        st.session_state["active_filters"] = filters

        if st.button("Apply", key="apply_top", type="primary", width="stretch"):
            st.session_state["active_filters"] = _prune_filters(filters)
            st.session_state["current_page"] = 1
            st.rerun()

    return filters  # type: ignore[no-any-return]


def _column_guide_markdown(columns: Sequence[str]) -> str:
    """A one-line-per-column glossary for the columns currently on screen."""
    rows = [
        f"- **{COLUMN_DISPLAY_NAMES.get(column, column)}** — {COLUMN_HELP[column]}"
        for column in columns
        if column in COLUMN_HELP
    ]
    return "\n".join(rows)


def _sync_time_text(raw: str | None) -> str:
    """Render a stored sync timestamp, tolerating malformed metadata."""
    if not raw:
        return "never"
    try:
        return datetime.fromtimestamp(float(raw)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError, OSError):
        return "an unknown time"


def _screener_table_height(row_count: int) -> int:
    """Cap the table so page chrome stays visible in a normal viewport."""
    return min(44 * row_count + 44, SCREENER_TABLE_MAX_HEIGHT)


def render_screener_table() -> None:
    """Render the main screener table with controls using DB-level filtering."""
    store = get_store()

    ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([2, 2, 1, 1])

    with ctrl_col1:
        view_preset = st.selectbox(
            "📋 View",
            options=list(VIEW_PRESETS.keys()),
            index=list(VIEW_PRESETS.keys()).index(
                st.session_state.get("view_preset", "Overview")
            ),
            key="view_preset_select",
        )
        st.session_state["view_preset"] = view_preset

    with ctrl_col2:
        sort_options = ["None"] + [
            COLUMN_DISPLAY_NAMES.get(c, c) for c in NUMERIC_FILTER_COLUMNS
        ]
        sort_keys = ["None"] + NUMERIC_FILTER_COLUMNS

        current_sort = st.session_state.get("sort_column")
        sort_idx = 0
        if current_sort and current_sort in sort_keys:
            sort_idx = sort_keys.index(current_sort)

        sort_selection = st.selectbox(
            "📊 Sort by",
            options=sort_options,
            index=sort_idx,
            key="sort_select",
        )
        sort_column = (
            sort_keys[sort_options.index(sort_selection)]
            if sort_selection != "None"
            else None
        )
        st.session_state["sort_column"] = sort_column

    with ctrl_col3:
        sort_ascending = st.selectbox(
            "Order",
            options=["Ascending", "Descending"],
            index=0 if st.session_state.get("sort_ascending", True) else 1,
            key="sort_order",
        )
        st.session_state["sort_ascending"] = sort_ascending == "Ascending"

    with ctrl_col4:
        page_size = st.selectbox(
            "Per page",
            options=PAGE_SIZE_OPTIONS,
            index=PAGE_SIZE_OPTIONS.index(
                st.session_state.get("page_size", DEFAULT_PAGE_SIZE)
            ),
            key="page_size_select",
        )
        st.session_state["page_size"] = page_size

    active_filters = st.session_state.get("active_filters", {})
    search_query = st.session_state.get("search_query", "")
    current_page = st.session_state.get("current_page", 1)

    result = store.get_stocks(
        filters=active_filters,
        search_query=search_query,
        sort_column=sort_column,
        sort_ascending=st.session_state.get("sort_ascending", True),
        page=current_page,
        page_size=page_size,
    )
    page_rows, total_pages, total_matching = result

    if result.warnings:
        st.warning("\n".join(f"⚠️ {warning}" for warning in result.warnings))

    if store.get_metadata("last_sync_status") == "failed":
        error = store.get_metadata("last_sync_error") or "unknown error"
        since = _sync_time_text(store.get_metadata("last_successful_sync_at"))
        st.error(
            f"⚠️ **Last background sync failed** ({error}). "
            f"Showing the snapshot from {since}."
        )

    if total_matching == 0 and (active_filters or search_query):
        st.warning("⚠️ **No stocks match your current filters.**")

    preset_cols = VIEW_PRESETS.get(view_preset, [])
    if not preset_cols:
        visible_cols = [
            "symbol",
            "description",
            "exchange",
            "market_cap",
            "price",
            "pe_ratio",
            "dividend_yield_pct",
            "beta",
        ]
    else:
        visible_cols = [c for c in preset_cols]

    if not page_rows:
        st.info("No stocks to display. Run the worker to populate data.")
        return

    page_df = pd.DataFrame(page_rows)

    # Rows in HedgeFollow's largest buys get the accent tint; the rest zebra-stripe
    # so a wide sheet of numbers still reads row by row.
    if "hedge_fund_buys" in page_df.columns:
        hf_mask = page_df["hedge_fund_buys"].fillna(0).astype(int).eq(1)
    else:
        hf_mask = pd.Series(False, index=page_df.index)

    raw_symbols = [row.get("symbol") for row in page_rows]

    watchlist_symbols = set(store.get_watchlist_symbols())
    if "symbol" in page_df.columns:
        page_df["symbol"] = page_df["symbol"].apply(
            lambda x: f"⭐ {x}" if x in watchlist_symbols else x
        )

    rename_map = {
        c: COLUMN_DISPLAY_NAMES.get(c, c) for c in visible_cols if c in page_df.columns
    }
    visible_cols = [c for c in visible_cols if c in page_df.columns]
    display_df = page_df[visible_cols].rename(columns=rename_map)

    display_df = _format_display_frame(display_df)

    def _row_style(row: pd.Series) -> list[str]:
        if bool(hf_mask.loc[row.name]):
            return ["background-color: rgba(99, 102, 241, 0.16)"] * len(row)
        if row.name % 2:
            return ["background-color: rgba(248, 250, 252, 0.03)"] * len(row)
        return [""] * len(row)

    # The report speaks for the whole filtered universe, not just this page.
    report_rows, _, _ = store.get_stocks(
        filters=active_filters,
        search_query=search_query,
        sort_column=sort_column,
        sort_ascending=st.session_state.get("sort_ascending", True),
        page=1,
        page_size=max(total_matching, 1),
    )
    prompt = report.screener_report_prompt(
        report_rows, total_matching, active_filters, search_query, view_preset
    )
    report_view.render_llm_report(
        scope_key="screener-llm-report",
        heading="🤖 AI report",
        prompt=prompt,
    )
    selection = st.dataframe(
        display_df.style.apply(_row_style, axis=1),
        width="stretch",
        hide_index=True,
        row_height=44,
        height=_screener_table_height(len(display_df)),
        on_select="rerun",
        selection_mode="single-row",
        key=_table_key("screener_table"),
    )
    selected_rows = getattr(getattr(selection, "selection", None), "rows", None) or []
    if selected_rows:
        index = selected_rows[0]
        if 0 <= index < len(raw_symbols) and raw_symbols[index]:
            open_symbol(str(raw_symbols[index]))
            st.rerun()

    if total_pages > 1:
        pag_col1, pag_col2, pag_col3, pag_col4, pag_col5 = st.columns([1, 1, 3, 1, 1])
        with pag_col1:
            if st.button("⏮ First", key="page_first", disabled=current_page <= 1):
                st.session_state["current_page"] = 1
                st.rerun()
        with pag_col2:
            if st.button("◀ Prev", key="page_prev", disabled=current_page <= 1):
                st.session_state["current_page"] = max(1, current_page - 1)
                st.rerun()
        with pag_col3:
            st.markdown(
                f'<div class="pagination-info">Page {current_page} of {total_pages} · {total_matching:,} results</div>',
                unsafe_allow_html=True,
            )
        with pag_col4:
            if st.button(
                "Next ▶", key="page_next", disabled=current_page >= total_pages
            ):
                st.session_state["current_page"] = min(total_pages, current_page + 1)
                st.rerun()
        with pag_col5:
            if st.button(
                "Last ⏭", key="page_last", disabled=current_page >= total_pages
            ):
                st.session_state["current_page"] = total_pages
                st.rerun()

    full_rows, _, full_count = store.get_stocks(
        filters=active_filters,
        search_query=search_query,
        page=1,
        page_size=10000,
    )
    full_df = pd.DataFrame(full_rows)
    csv_data = full_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=f"📥 Download CSV ({full_count:,} rows)",
        data=csv_data,
        file_name=f"stonks_screener_{time.strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        key="download_csv",
    )

    guide = _column_guide_markdown(visible_cols)
    if guide:
        with st.expander("📖 What the columns mean"):
            st.markdown(guide)


def _watchlist_stock(store: SQLiteStore, ticker: str) -> dict[str, Any] | None:
    """Look up a typed ticker in the stored universe, ignoring active filters."""
    rows, _, _ = store.get_stocks(
        filters={"symbol": {"values": [ticker]}},
        page=1,
        page_size=10,
    )
    return next((row for row in rows if is_stock_row(row)), None)


def _clear_watchlist_editor_state() -> None:
    for key in ("wl_symbol_ticker", "wl_edit_index"):
        st.session_state.pop(key, None)


def _commit_watchlist_symbol(
    store: SQLiteStore, symbols: list[str], editing: int | None
) -> None:
    ticker = str(st.session_state.get("wl_symbol_ticker") or "").strip().upper()
    if not ticker:
        st.warning("Enter one ticker symbol.")
        return
    if _watchlist_stock(store, ticker) is None:
        st.warning(f"{ticker} is not a stock in the stored universe.")
        return

    if editing is not None and 0 <= editing < len(symbols):
        previous = symbols[editing]
        if ticker != previous and ticker in symbols:
            st.warning(f"{ticker} is already on the watchlist.")
            return
        if ticker != previous:
            store.remove_from_watchlist(previous)
    elif ticker in symbols:
        st.warning(f"{ticker} is already on the watchlist.")
        return

    store.add_to_watchlist(ticker)
    _clear_watchlist_editor_state()
    st.rerun()


def _render_watchlist_editor(store: SQLiteStore, symbols: list[str]) -> None:
    """Backtest-style symbol list with inline edit/delete and an add panel."""
    st.caption(f"{len(symbols)} symbols")
    if not symbols:
        st.caption("No symbols yet. Add one below.")

    for index, symbol in enumerate(symbols):
        info_col, edit_col, delete_col = st.columns([3, 1, 1])
        info_col.markdown(f"**{symbol}**")
        if edit_col.button("✏️", key=f"wl_edit_symbol_{index}", help="Edit this symbol"):
            st.session_state["wl_symbol_ticker"] = symbol
            st.session_state["wl_edit_index"] = index
            st.rerun()
        if delete_col.button(
            "🗑", key=f"wl_delete_symbol_{index}", help="Remove this symbol"
        ):
            store.remove_from_watchlist(symbol)
            _clear_watchlist_editor_state()
            st.rerun()

    editing = st.session_state.get("wl_edit_index")
    editing = int(editing) if editing is not None else None
    if editing is not None and not 0 <= editing < len(symbols):
        editing = None
    label = "Edit symbol" if editing is not None else "Add symbol"

    with st.expander(
        label, expanded=editing is not None, key="watchlist_symbol_editor"
    ):
        st.text_input(
            "Ticker",
            key="wl_symbol_ticker",
            placeholder="AAPL",
        )
        action_col, cancel_col = st.columns([1, 1])
        with action_col:
            if st.button(
                "Save changes" if editing is not None else "Add",
                key="wl_symbol_save",
            ):
                _commit_watchlist_symbol(store, symbols, editing)
        if editing is not None:
            with cancel_col:
                if st.button("Cancel", key="wl_symbol_cancel"):
                    _clear_watchlist_editor_state()
                    st.rerun()


def render_watchlist_tab() -> None:
    """Render the watchlist table and its symbol editor."""
    store = get_store()
    watchlist = store.get_watchlist()
    watchlist_symbols = [item["symbol"] for item in watchlist]

    if watchlist_symbols:
        page_rows, _, _ = store.get_stocks(
            filters={"symbol": {"values": watchlist_symbols}},
            page=1,
            page_size=len(watchlist_symbols),
        )
        stock_rows = [row for row in page_rows if is_stock_row(row)]
        watchlist_symbols = [row["symbol"] for row in stock_rows]
        watchlist_df = pd.DataFrame(stock_rows)
    else:
        watchlist_df = pd.DataFrame()

    if not watchlist_df.empty:
        preset = st.selectbox(
            "📋 View",
            options=list(VIEW_PRESETS.keys()),
            index=list(VIEW_PRESETS.keys()).index(
                st.session_state.get("watchlist_view_preset", "Overview")
            ),
            key="watchlist_view_preset_select",
        )
        st.session_state["watchlist_view_preset"] = preset

        # A symbol with unread alerts is marked here, so the badge's count has
        # somewhere to point once the banner is dismissed.
        alert_counts = store.unread_alert_counts()
        view_cols = [
            c for c in VIEW_PRESETS.get(preset, []) if c in watchlist_df.columns
        ]
        display_wl = watchlist_df[view_cols].rename(
            columns={c: COLUMN_DISPLAY_NAMES.get(c, c) for c in view_cols}
        )
        if "Symbol" in display_wl.columns:
            marker = [
                str(alert_counts[symbol]) if alert_counts.get(symbol) else "—"
                for symbol in watchlist_df["symbol"]
            ]
            display_wl.insert(1, "Alerts", marker)
        display_wl = _format_display_frame(display_wl)

        watchlist_selection = st.dataframe(
            display_wl,
            width="stretch",
            hide_index=True,
            row_height=44,
            on_select="rerun",
            selection_mode="single-row",
            key=_table_key("watchlist_table"),
        )
        picked_rows = (
            getattr(getattr(watchlist_selection, "selection", None), "rows", None) or []
        )
        if picked_rows:
            index = picked_rows[0]
            if 0 <= index < len(watchlist_df):
                open_symbol(str(watchlist_df.iloc[index]["symbol"]))
                st.rerun()

        csv = watchlist_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label=f"📥 Download Watchlist CSV ({len(watchlist_df)} stocks)",
            data=csv,
            file_name=f"stonks_watchlist_{time.strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            key="download_watchlist",
        )

    st.divider()
    _render_watchlist_editor(store, watchlist_symbols)


def _portfolio_instrument(store: SQLiteStore, ticker: str) -> dict[str, Any] | None:
    """Look up a typed ticker in the stored universe, ETFs included."""
    rows, _, _ = store.get_stocks(
        filters={"symbol": {"values": [ticker]}},
        page=1,
        page_size=10,
    )
    return next((row for row in rows if row["symbol"] == ticker), None)


def _clear_portfolio_editor_state() -> None:
    for key in (
        "pf_symbol_ticker",
        "pf_quantity",
        "pf_price",
        "pf_currency",
        "pf_notes",
    ):
        st.session_state.pop(key, None)


def render_portfolio_tab() -> None:
    """Show USD holdings totals, manual lots and a one-click holdings backtest."""
    store = get_store()
    summary, stale = portfolio_snapshot(store)
    for currency in stale:
        st.warning(f"⚠️ Stale {currency}→USD rate; values may be out of date.")
    if summary.excluded_symbols:
        count = len(summary.excluded_symbols)
        st.warning(
            f"{count} holding{'s' if count != 1 else ''} excluded from USD totals: "
            f"{', '.join(summary.excluded_symbols)} — price or FX rate unavailable."
        )

    symbols, weights = backtest_allocation(summary)
    factor = portfolio_correlation_factor(store, symbols, weights)
    value_col, pnl_col, daily_col, cost_col, corr_col = st.columns(5)
    value_col.metric(
        "Total value (USD)",
        f"${summary.total_value_usd:,.2f}"
        if summary.total_value_usd is not None
        else "—",
    )
    pnl_col.metric(
        "Unrealized P&L (USD)",
        _signed_money(summary.unrealized_pnl_usd),
        delta=(
            f"{summary.unrealized_pct:+.2f}%"
            if summary.unrealized_pct is not None
            else None
        ),
    )
    daily_col.metric("Daily P&L (USD)", _signed_money(summary.daily_pnl_usd))
    cost_col.metric(
        "Cost basis (USD)",
        f"${summary.total_cost_usd:,.2f}"
        if summary.total_cost_usd is not None
        else "—",
    )
    corr_col.metric(
        "Portfolio correlation",
        f"{factor:+.2f}" if factor is not None else "—",
        help=(
            "Weighted average pairwise correlation of monthly returns; "
            "higher means holdings move together."
        ),
    )

    rows: list[dict[str, Any]] = []
    for holding in summary.holdings:
        rows.append(
            {
                "Instrument": f"{holding.symbol} — {holding.description}",
                "Position": holding.quantity,
                "Last": _money(holding.last, holding.currency),
                "Change %": _fmt_pct(holding.change_pct),
                "Cost Basis": _money(holding.cost_native, holding.currency),
                "Market Value": _money(holding.market_native, holding.currency),
                "Avg Price": _money(holding.avg_price, holding.currency),
                "Daily P&L": _money(holding.daily_pnl_native, holding.currency),
                "Unrealized P&L": _money(holding.unrealized_native, holding.currency),
                "Currency": holding.currency,
                "USD Value": _money(holding.market_usd, "USD"),
            }
        )
    if rows:
        frame = pd.DataFrame(rows)
        selection = st.dataframe(
            frame,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=_table_key("portfolio_table"),
        )
        picked = getattr(getattr(selection, "selection", None), "rows", None) or []
        if picked and 0 <= picked[0] < len(rows):
            open_symbol(summary.holdings[picked[0]].symbol)
            st.rerun()
        st.download_button(
            "📥 Download Portfolio CSV",
            data=frame.to_csv(index=False).encode("utf-8"),
            file_name=f"stonks_portfolio_{time.strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            key="download_portfolio",
        )
    else:
        st.caption("No holdings yet. Add a lot below.")

    if st.button("⚡ Backtest my portfolio", key="pf_backtest"):
        settings = holdings_settings_from_summary(summary)
        if settings is None:
            st.warning("No priced holdings to backtest yet.")
        else:
            try:
                result = run_configured_backtest(store, settings)
            except (OSError, ValueError) as exc:
                st.error(f"Backtest failed: {exc}")
            else:
                st.session_state[_RESULT_KEY] = result
                st.session_state[_SETTINGS_KEY] = settings
                st.session_state["page"] = "backtest"
                st.rerun()

    positions = store.get_positions()
    with st.expander("💼 Lots", expanded=False):
        if not positions:
            st.caption("No lots yet. Add one below.")
        for lot in positions:
            info_col, action_col = st.columns([5, 1])
            added = datetime.fromtimestamp(float(lot["added_at"])).strftime("%Y-%m-%d")
            info_col.markdown(
                f"**{lot['symbol']}** · {lot['quantity']:g} × "
                f"{_money(lot['price'], lot['currency'])} · {added}"
            )
            if lot["notes"]:
                info_col.caption(lot["notes"])
            if action_col.button(
                "🗑", key=f"pf_delete_{lot['id']}", help="Delete this lot"
            ):
                store.delete_position(lot["id"])
                st.rerun()

    with st.expander("Add lot", expanded=False):
        st.text_input("Ticker", key="pf_symbol_ticker", placeholder="MSFT")
        st.number_input(
            "Quantity", min_value=0.0, value=1.0, step=1.0, key="pf_quantity"
        )
        st.number_input(
            "Price paid",
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.2f",
            key="pf_price",
        )
        st.selectbox(
            "Trade currency",
            ["USD", *sorted(CONVERTIBLE_CURRENCIES - {"USD"})],
            key="pf_currency",
        )
        st.text_input("Notes (optional)", key="pf_notes")
        if st.button("Add lot", key="pf_add_lot"):
            ticker = str(st.session_state.get("pf_symbol_ticker") or "").strip().upper()
            quantity = float(st.session_state.get("pf_quantity") or 0.0)
            price = float(st.session_state.get("pf_price") or 0.0)
            currency = str(st.session_state.get("pf_currency") or "USD").strip().upper()
            notes = str(st.session_state.get("pf_notes") or "").strip()
            try:
                validate_lot(ticker, quantity, price, currency)
            except ValueError as exc:
                st.warning(str(exc))
            else:
                if _portfolio_instrument(store, ticker) is None:
                    st.warning(f"{ticker} is not in the stored universe.")
                else:
                    store.add_position(ticker, quantity, price, currency, notes)
                    _clear_portfolio_editor_state()
                    st.rerun()


# ── Main App ─────────────────────────────────────────────────────────


def render_pipeline_hud(sync_info: dict[str, Any]) -> None:
    """Render a premium HUD showing data pipeline metrics."""
    if not sync_info or not sync_info.get("last_run"):
        return

    last_dt = datetime.fromtimestamp(sync_info["last_run"]).strftime("%H:%M:%S")
    success = sync_info["success_count"]
    fundamentals = sync_info["fundamentals_count"]
    failed = sync_info["failed_count"]
    total = sync_info["total_symbols"]
    completion = (success / max(1, total)) * 100
    fundamentals_completion = (fundamentals / max(1, total)) * 100

    st.markdown(
        """
        <style>
        .hud-card {
            background: #1e293b;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
        }
        .hud-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }
        .hud-title {
            font-size: 0.9rem;
            font-weight: 600;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .hud-metrics {
            display: flex;
            gap: 2rem;
            flex-wrap: wrap;
        }
        .metric-group {
            display: flex;
            flex-direction: column;
        }
        .metric-value {
            font-size: 1.75rem;
            font-weight: 700;
            color: #f8fafc;
            line-height: 1;
            margin-bottom: 0.25rem;
        }
        .metric-label {
            font-size: 0.75rem;
            color: #64748b;
        }
        .progress-container {
            width: 100%;
            height: 6px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 3px;
            margin-top: 1rem;
            overflow: hidden;
        }
        .progress-bar {
            height: 100%;
            background: #6366f1;
            border-radius: 3px;
            transition: width 0.5s ease-in-out;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        st.markdown(
            f"""
            <div class="hud-card">
                <div class="hud-header">
                    <div class="hud-title">📡 Data Pipeline HUD</div>
                </div>
                <div class="hud-metrics">
                    <div class="metric-group">
                        <div class="metric-value">{completion:.1f}%</div>
                        <div class="metric-label">Universe Coverage</div>
                    </div>
                    <div class="metric-group">
                        <div class="metric-value">{fundamentals_completion:.1f}%</div>
                        <div class="metric-label">Fundamental Data</div>
                    </div>
                    <div class="metric-group">
                        <div class="metric-value">{success:,}</div>
                        <div class="metric-label">Local Hits</div>
                    </div>
                    <div class="metric-group">
                        <div class="metric-value">{failed}</div>
                        <div class="metric-label">Sync Misses</div>
                    </div>
                    <div class="metric-group">
                        <div class="metric-value">{last_dt}</div>
                        <div class="metric-label">Last Last Heartbeat</div>
                    </div>
                    <div class="metric-group">
                        <div class="metric-value">{total:,}</div>
                        <div class="metric-label">Universe</div>
                    </div>
                </div>
                <div class="progress-container">
                    <div class="progress-bar" style="width: {completion}%"></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _default_screen() -> dict[str, Any]:
    """Return the screen the app opens with (the sanity check's reference)."""
    return default_screen()


def _init_session_state() -> None:
    """Seed session state with the default screen and paging settings."""
    screen = _default_screen()
    defaults: dict[str, Any] = {
        "active_filters": screen["filters"],
        "view_preset": screen["view_preset"],
        "sort_column": screen["sort_column"],
        "sort_ascending": screen["sort_ascending"],
        "current_page": 1,
        "page_size": DEFAULT_PAGE_SIZE,
        "page": "screener",
        "detail_symbol": None,
        "selection_epoch": 0,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _ago(epoch: float | None) -> str:
    """Relative age of an alert, e.g. "12m ago" or "3d ago"."""
    if not epoch:
        return ""
    delta = max(0.0, time.time() - epoch)
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def render_sanity_banner(store: SQLiteStore) -> None:
    """Report the reference-site checks that diverged, if any did."""
    report = sanity.load_report(store)
    if not report:
        return
    failures = [result for result in report["results"] if result.get("ok") is False]
    if not failures:
        return

    with st.container(key="sanity-banner"):
        st.error(
            f"Cross-check failed on {len(failures)} platform"
            f"{'s' if len(failures) != 1 else ''} — a provider or model may have "
            "diverged from what the app expects.",
            icon="⚠️",
        )
        for failure in failures:
            st.markdown(
                f"**{failure.get('platform', '?')}** · {failure.get('check', '')} — "
                f"{failure.get('detail', '')}"
            )
        st.caption(
            "Checked "
            f"{_ago(report.get('checked_at'))} by the worker; "
            "nothing here changes the data on screen."
        )


def _buy_opportunity_lines(row: dict[str, Any]) -> list[str]:
    """The price and fair-value lines shown for a screener buy signal."""
    price = row.get("price")
    low = row.get("week_52_low")
    dcf = row.get("dcf_fair_value")
    lynch = row.get("lynch_fair_value")
    parts = [f"Price {_fmt_number(price, 2)} vs 52w low {_fmt_number(low, 2)}"]
    if row.get("below_both_fair_values"):
        parts.append(
            f"below DCF {_fmt_number(dcf, 2)} and Lynch {_fmt_number(lynch, 2)}"
        )
    elif dcf is not None or lynch is not None:
        fair_bits = []
        if dcf is not None:
            fair_bits.append(f"DCF {_fmt_number(dcf, 2)}")
        if lynch is not None:
            fair_bits.append(f"Lynch {_fmt_number(lynch, 2)}")
        parts.append("fair value " + ", ".join(fair_bits))
    return parts


def _notification_groups(
    alerts: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    watchlist_symbols: set[str],
    held_symbols: set[str],
) -> list[tuple[str, dict[str, list[dict[str, Any]]]]]:
    """Collect every notification under its symbol; tracked tickers come first."""
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for alert in alerts:
        groups.setdefault(alert["symbol"], {"alerts": [], "opportunities": []})[
            "alerts"
        ].append(alert)
    for row in opportunities:
        groups.setdefault(row["symbol"], {"alerts": [], "opportunities": []})[
            "opportunities"
        ].append(row)
    return sorted(
        groups.items(),
        key=lambda item: (
            item[0] not in (watchlist_symbols | held_symbols),
            not item[1]["opportunities"],
            -max((alert["created_at"] for alert in item[1]["alerts"]), default=0),
        ),
    )


def _group_severity_icon(group: dict[str, list[dict[str, Any]]]) -> str:
    """Summarise a ticker's notifications with its strongest severity icon."""
    icons = {"good": "🟢", "warn": "🟠", "info": "🔵"}
    priority = {"warn": 0, "good": 1, "info": 2}
    severities = [alert["severity"] for alert in group["alerts"]]
    if group["opportunities"]:
        severities.append("good")
    if not severities:
        return "•"
    strongest = min(severities, key=lambda severity: priority.get(severity, 3))
    return icons.get(strongest, "•")


def render_notifications(store: SQLiteStore) -> None:
    """Show screener, watchlist and portfolio notifications together."""
    held_symbols = set(store.get_position_symbols())
    watchlist_symbols = set(store.get_watchlist_symbols())
    visible_symbols = set(
        store.get_stock_symbols(
            filters=st.session_state.get("active_filters") or {},
            search_query=st.session_state.get("search_query") or "",
        )
    ) | set(store.get_monitored_symbols())
    alerts = [
        alert for alert in store.get_alerts() if alert["symbol"] in visible_symbols
    ]
    opportunities = [
        row
        for row in store.get_buy_opportunities(limit=8)
        if row["symbol"] in visible_symbols
    ]
    persisted_buys = {
        alert["symbol"] for alert in alerts if alert.get("kind") == "buy_opportunity"
    }
    snapshot_buys = [
        row for row in opportunities if row["symbol"] not in persisted_buys
    ]
    count = len(
        {alert["symbol"] for alert in alerts} | {row["symbol"] for row in snapshot_buys}
    )
    if not count:
        return

    with st.expander(f"🔔 Notifications ({count})", expanded=False):
        below_both = [row for row in snapshot_buys if row.get("below_both_fair_values")]
        if snapshot_buys:
            if not st.session_state.get("buy_opps_toasted"):
                if below_both:
                    symbols = ", ".join(row["symbol"] for row in below_both[:3])
                    st.toast(
                        f"Buy opportunities below DCF and Lynch: {symbols}", icon="📉"
                    )
                else:
                    st.toast(
                        f"{len(snapshot_buys)} screener stocks near 52-week lows",
                        icon="📉",
                    )
                st.session_state["buy_opps_toasted"] = True
            headline = f"{len(snapshot_buys)} buy opportunities near 52-week lows"
            if below_both:
                headline += (
                    f" · {len(below_both)} below both DCF and Peter Lynch fair value"
                )
            watch_count = sum(
                row["symbol"] in watchlist_symbols for row in snapshot_buys
            )
            if watch_count:
                headline += f" · {watch_count} on your watchlist"
            held_count = sum(row["symbol"] in held_symbols for row in snapshot_buys)
            if held_count:
                headline += f" · {held_count} in your portfolio"
            st.success(headline, icon="📉")

        if alerts:
            st.info(
                f"{len(alerts)} unread alert{'s' if len(alerts) != 1 else ''} "
                f"across {count} ticker{'s' if count != 1 else ''}",
                icon="🔔",
            )

        severity_icons = {"good": "🟢", "warn": "🟠", "info": "🔵"}
        for symbol, group in _notification_groups(
            alerts, snapshot_buys, watchlist_symbols, held_symbols
        ):
            symbol_col, text_col = st.columns([1, 7])
            with symbol_col:
                if st.button(
                    f"{symbol} ▸",
                    key=f"notification_open_{symbol}",
                    help=f"Open {symbol}",
                ):
                    open_symbol(symbol)
                    st.rerun()
            with text_col:
                header = f"{_group_severity_icon(group)} **{symbol}**"
                if group["opportunities"]:
                    description = group["opportunities"][0].get("description") or ""
                    if description:
                        header += f" · {description}"
                    if symbol in watchlist_symbols:
                        header += " · ⭐ on watchlist"
                if symbol in held_symbols:
                    header += " · 💼 in portfolio"
                st.markdown(header)
                for row in group["opportunities"]:
                    st.caption(" · ".join(_buy_opportunity_lines(row)))
                for alert in group["alerts"]:
                    icon = severity_icons.get(alert["severity"], "•")
                    st.markdown(f"{icon} **{alert['title']}**")
                    meta = [alert.get("detail") or "", _ago(alert.get("created_at"))]
                    st.caption(" · ".join(part for part in meta if part))

        if alerts and st.button("Mark all read", key="alerts_mark_read"):
            store.mark_alerts_seen([alert["id"] for alert in alerts])
            st.rerun()


def main() -> None:
    """Main Streamlit app entry point."""
    store = get_store()
    _init_session_state()

    # The default screener is always offered as a saved screen.
    if not store.list_screens():
        screen = _default_screen()
        store.save_screen(
            "Default Screener",
            screen["filters"],
            screen["view_preset"],
            screen["sort_column"],
            screen["sort_ascending"],
        )

    render_notifications(store)
    render_header(store)
    render_sidebar_filters()

    sync_info = store.get_last_sync_info()
    render_pipeline_hud(sync_info)
    render_sanity_banner(store)

    if st.session_state.get("page") == "detail" and st.session_state.get(
        "detail_symbol"
    ):
        if st.button("← Back to screener", key="detail_back"):
            close_detail()
            st.rerun()
        render_detail_page(store, st.session_state["detail_symbol"])
        return

    if st.session_state.get("page") == "backtest":
        if st.button("← Back to screener", key="backtest_back"):
            st.session_state["page"] = "screener"
            st.rerun()
        render_backtest_tab(store)
        return

    # Main content tabs; alerts live in the collapsed Notifications surface
    # and cover the active screen, the watchlist and portfolio holdings.
    tab_screener, tab_watchlist, tab_portfolio, tab_backtest = st.tabs(
        ["📊 Screener", "⭐ Watchlist", "💼 Portfolio", "🧪 Backtest"]
    )

    with tab_screener:
        # Render the new top-level filters grid
        render_top_filters()

        # engine is already initialized, but we need to pass the CURRENT filtered DF to the table renderer
        # or let the table renderer do its own filtering/search
        render_screener_table()

    with tab_watchlist:
        render_watchlist_tab()

    with tab_portfolio:
        render_portfolio_tab()

    with tab_backtest:
        render_backtest_tab(store)

    # Footer
    st.markdown(
        """
    <div class="app-footer">
        Stonks Screener v0.1.0 · Data from <a href="https://stockanalysis.com" style="color: #6366f1;">StockAnalysis.com</a> ·
        Hedge fund list from <a href="https://hedgefollow.com/Largest-Hedge-Fund-Buys.php" style="color: #6366f1;">HedgeFollow</a> ·
        Built with <a href="https://streamlit.io" style="color: #6366f1;">Streamlit</a>
    </div>
    """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    # A Streamlit script run has its own globals. When the importable app module
    # is already loaded, use its entry point so patched view helpers are honoured.
    import sys

    _app_module = sys.modules.get("stonks.app") or sys.modules[__name__]
    _app_module.main()
