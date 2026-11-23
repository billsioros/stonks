"""Stonks — Streamlit Stock Screener App.

Run with: streamlit run src/stonks/app.py
"""

import base64
import logging
import math
import re
import time
from collections.abc import Sequence
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import streamlit as st

from stonks import report, report_view, sanity
from stonks.backtest_view import render_backtest_tab
from stonks.config import (
    COLUMN_DISPLAY_NAMES,
    COLUMN_HELP,
    DEFAULT_PAGE_SIZE,
    ENUM_FILTER_COLUMNS,
    NUMERIC_FILTER_COLUMNS,
    PAGE_SIZE_OPTIONS,
    VIEW_PRESETS,
)
from stonks.detail_view import render_detail_page
from stonks.presets import POPULAR_SCREENS, default_screen
from stonks.store import SQLiteStore

logger = logging.getLogger(__name__)

# ── Page configuration ──────────────────────────────────────────────
st.set_page_config(
    page_title="Stonks",
    page_icon="src/stonks/assets/favicon.png",
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
    max-width: 100% !important;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: var(--bg-secondary) !important;
    border-right: 1px solid var(--border-color) !important;
}

section[data-testid="stSidebar"] .block-container {
    padding-top: 1rem !important;
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
}

.sk-mark img {
    width: 100%;
    height: 100%;
    object-fit: contain;
    image-rendering: -webkit-optimize-contrast;
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

/* Footer */
.app-footer {
    text-align: center;
    color: var(--text-muted);
    font-size: 0.75rem;
    padding: 1.5rem 0;
    border-top: 1px solid var(--border-color);
    margin-top: 2rem;
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
    """Render the 13F flag: a whale when the stock is a top hedge-fund buy."""
    if _is_missing(val):
        return "—"
    return "🐋" if val else "—"


def _fmt_upside(val: float | None) -> str:
    """Render an upside with its direction: green for gains, red for losses."""
    if _is_missing(val):
        return "—"
    return f"{'🟢' if val >= 0 else '🔴'} {val:+.1f}%"


def _fmt_current_ratio(val: float | None) -> str:
    """Render the current ratio, marking liquidity below 1."""
    if _is_missing(val):
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


@lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    """Return the bundled favicon as a data URI for the masthead."""
    path = Path(__file__).parent / "assets" / "favicon.png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def render_header() -> None:
    """Render the masthead: brand on the left, data source on the right."""
    st.markdown(
        f"""
    <div class="sk-head">
        <div class="sk-brand">
            <div class="sk-mark"><img src="{_logo_data_uri()}" alt="Stonks"></div>
            <h1>Stonks</h1>
        </div>
        <div class="sk-meta">
            <p>Fundamental screener · data from StockAnalysis.com</p>
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


def _screen_card(
    key: str,
    title: str,
    description: str | None,
    *,
    allow_delete: bool = False,
) -> tuple[bool, bool]:
    """Render one screen as a card and return (load_clicked, delete_clicked)."""
    with st.container(key=f"screen-{key}"):
        ratios = [5, 1, 1] if allow_delete else [6, 1]
        cols = st.columns(ratios)
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
                use_container_width=True,
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
            if st.button(
                "🧹 Reset All", key="reset_filters_top", use_container_width=True
            ):
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

        if st.button(
            "Apply", key="apply_top", type="primary", use_container_width=True
        ):
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
        height=min(44 * len(display_df) + 44, 900),
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


def render_watchlist_tab() -> None:
    """Render the watchlist management tab."""
    store = get_store()
    st.markdown(
        '<div class="section-header">⭐ Watchlist</div>', unsafe_allow_html=True
    )

    query = st.text_input(
        "Search symbol or company",
        key="watchlist_search",
        placeholder="Type a symbol or company name, e.g. AAPL or Apple...",
    )

    # The universe is too large for a plain selectbox, so the typed query is
    # resolved against the database and the best matches are offered instead.
    matches: list[dict[str, Any]] = []
    picked: str | None = None
    if query.strip():
        matches, _, _ = store.get_stocks(search_query=query, page_size=8)
        if matches:
            labels = [
                f"{row['symbol']} · {row.get('description') or ''}".rstrip(" ·")
                for row in matches
            ]
            choice = st.selectbox(
                "Matches",
                options=labels,
                key="watchlist_match",
                label_visibility="collapsed",
            )
            picked = matches[labels.index(choice)]["symbol"]
        else:
            st.caption("No symbol or company matches that search.")

    add_clicked = st.button(
        "⭐ Add to watchlist",
        key="watchlist_add_btn",
        type="primary",
        disabled=picked is None,
    )
    if add_clicked and picked:
        store.add_to_watchlist(picked)
        st.toast(f"⭐ Added {picked} to watchlist!", icon="✅")
        time.sleep(0.5)
        st.rerun()

    st.divider()

    watchlist = store.get_watchlist()
    if not watchlist:
        st.info(
            "Your watchlist is empty. Add stocks using the selector above or from the screener."
        )
        return

    watchlist_symbols = [item["symbol"] for item in watchlist]

    if watchlist_symbols:
        page_rows, _, _ = store.get_stocks(
            filters={"symbol": {"values": watchlist_symbols}},
            page=1,
            page_size=len(watchlist_symbols),
        )
        watchlist_df = pd.DataFrame(page_rows)
    else:
        watchlist_df = pd.DataFrame()

    if not watchlist_df.empty:
        # A symbol with unread alerts is marked here, so the badge's count has
        # somewhere to point once the banner is dismissed.
        alert_counts = store.unread_alert_counts()
        view_cols = [
            "symbol",
            "description",
            "market_cap",
            "pe_ratio",
            "roe_pct",
            "dividend_yield_pct",
            "price",
            "beta",
            "dcf_fair_value",
            "dcf_upside_pct",
            "lynch_fair_value",
            "lynch_upside_pct",
        ]
        view_cols = [c for c in view_cols if c in watchlist_df.columns]
        display_wl = watchlist_df[view_cols].copy()

        rename_map = {c: COLUMN_DISPLAY_NAMES.get(c, c) for c in view_cols}
        display_wl = display_wl.rename(columns=rename_map)

        if "Symbol" in display_wl.columns:
            marker = [
                str(alert_counts[symbol]) if alert_counts.get(symbol) else "—"
                for symbol in watchlist_df["symbol"]
            ]
            display_wl.insert(1, "Alerts", marker)

        if "Market Cap" in display_wl.columns:
            display_wl["Market Cap"] = display_wl["Market Cap"].apply(_fmt_market_cap)
        for col in display_wl.columns:
            if "%" in col:
                display_wl[col] = display_wl[col].apply(_fmt_pct)
            elif col in ("P/E", "Beta", "DCF Fair Value", "Lynch Fair Value"):
                display_wl[col] = display_wl[col].apply(lambda x: _fmt_number(x, 2))

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
    st.markdown("**Remove from watchlist:**")
    cols_per_row = 6
    for i in range(0, len(watchlist_symbols), cols_per_row):
        row_syms = watchlist_symbols[i : i + cols_per_row]
        cols = st.columns(cols_per_row)
        for j, sym in enumerate(row_syms):
            with cols[j]:
                if st.button(f"❌ {sym}", key=f"remove_wl_{sym}"):
                    store.remove_from_watchlist(sym)
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
        .hud-status {
            font-size: 0.8rem;
            padding: 2px 10px;
            border-radius: 999px;
            background: rgba(99, 102, 241, 0.12);
            color: #f8fafc;
            border: 1px solid rgba(99, 102, 241, 0.5);
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
                    <div class="hud-status">● Live Sync Active</div>
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


def render_alerts_banner() -> None:
    """Show the unread watchlist alerts; renders nothing when there are none."""
    store = get_store()
    alerts = store.get_alerts()
    if not alerts:
        return

    severity_icons = {"good": "🟢", "warn": "🟠", "info": "🔵"}
    with st.container(key="alerts-banner"):
        count = len(alerts)
        st.info(
            f"{count} unread alert{'s' if count != 1 else ''} for your watchlist",
            icon="🔔",
        )
        for alert in alerts:
            symbol_col, text_col = st.columns([1, 7])
            with symbol_col:
                if st.button(
                    f"{alert['symbol']} ▸",
                    key=f"alert_open_{alert['id']}",
                    help=f"Open {alert['symbol']}",
                ):
                    open_symbol(alert["symbol"])
                    st.rerun()
            with text_col:
                icon = severity_icons.get(alert["severity"], "•")
                st.markdown(f"{icon} **{alert['title']}**")
                meta = [alert.get("detail") or "", _ago(alert.get("created_at"))]
                st.caption(" · ".join(part for part in meta if part))
        if st.button("Mark all read", key="alerts_mark_read"):
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

    render_header()
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

    # Main content tabs; unread alerts are visible from anywhere in the app.
    unread = store.count_unread_alerts()
    watchlist_label = f"⭐ Watchlist ({unread})" if unread else "⭐ Watchlist"
    tab_screener, tab_watchlist, tab_backtest = st.tabs(
        ["📊 Screener", watchlist_label, "🧪 Backtest"]
    )

    with tab_screener:
        render_alerts_banner()

        # Render the new top-level filters grid
        render_top_filters()

        # engine is already initialized, but we need to pass the CURRENT filtered DF to the table renderer
        # or let the table renderer do its own filtering/search
        render_screener_table()

    with tab_watchlist:
        render_watchlist_tab()

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
    main()
