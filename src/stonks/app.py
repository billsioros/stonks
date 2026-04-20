"""Stonks — Streamlit Stock Screener App.

Run with: streamlit run src/stonks/app.py
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from stonks.cache import LocalCache
from stonks.config import (
    COLUMN_DISPLAY_NAMES,
    DEFAULT_PAGE_SIZE,
    ENUM_FILTER_COLUMNS,
    FINNHUB_API_KEY,
    NUMERIC_FILTER_COLUMNS,
    PAGE_SIZE_OPTIONS,
    VIEW_PRESETS,
)
from stonks.engine import ScreenerEngine
from stonks.metrics import MetricsProvider
from stonks.presets import POPULAR_SCREENS
from stonks.store import SQLiteStore
from stonks.universe import UniverseLoader

logger = logging.getLogger(__name__)

# ── Page configuration ──────────────────────────────────────────────
st.set_page_config(
    page_title="Stonks — Stock Screener",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ──────────────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

/* Root variables */
:root {
    --bg-primary: #0a0e1a;
    --bg-secondary: #111827;
    --bg-card: #1a1f35;
    --bg-card-hover: #222845;
    --accent-primary: #6366f1;
    --accent-secondary: #8b5cf6;
    --accent-tertiary: #a78bfa;
    --accent-glow: rgba(99, 102, 241, 0.15);
    --text-primary: #f1f5f9;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --border-color: #1e293b;
    --success: #10b981;
    --danger: #ef4444;
    --warning: #f59e0b;
    --gradient-1: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #a78bfa 100%);
    --gradient-2: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #1e293b 100%);
    --gradient-3: linear-gradient(135deg, #10b981 0%, #059669 100%);
}

/* Global styles */
.stApp {
    background: var(--bg-primary) !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

/* Main content area */
.main .block-container {
    padding-top: 1.5rem !important;
    max-width: 100% !important;
}

/* Sidebar styling */
section[data-testid="stSidebar"] {
    background: var(--bg-secondary) !important;
    border-right: 1px solid var(--border-color) !important;
}

section[data-testid="stSidebar"] .block-container {
    padding-top: 1rem !important;
}

/* Header styling */
.hero-header {
    background: var(--gradient-2);
    border: 1px solid var(--border-color);
    border-radius: 16px;
    padding: 1.5rem 2rem;
    margin-bottom: 1.5rem;
    position: relative;
    overflow: hidden;
}

.hero-header::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--gradient-1);
}

.hero-header h1 {
    font-size: 2rem !important;
    font-weight: 800 !important;
    background: var(--gradient-1);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0 !important;
    padding: 0 !important;
    letter-spacing: -0.02em;
}

.hero-subtitle {
    color: var(--text-secondary);
    font-size: 0.95rem;
    margin-top: 0.25rem;
    font-weight: 400;
}

/* Card styling */
.metric-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1.25rem;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
}

.metric-card:hover {
    background: var(--bg-card-hover);
    border-color: var(--accent-primary);
    box-shadow: 0 0 20px var(--accent-glow);
    transform: translateY(-2px);
}

.metric-card .label {
    color: var(--text-secondary);
    font-size: 0.8rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.5rem;
}

.metric-card .value {
    font-size: 1.8rem;
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.02em;
}

.metric-card .delta {
    font-size: 0.85rem;
    font-weight: 500;
    margin-top: 0.3rem;
}

.delta-positive { color: var(--success); }
.delta-negative { color: var(--danger); }

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

/* Screen preset cards */
.preset-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 1rem 1.25rem;
    cursor: pointer;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    margin-bottom: 0.5rem;
}

.preset-card:hover {
    background: var(--bg-card-hover);
    border-color: var(--accent-primary);
    box-shadow: 0 4px 12px var(--accent-glow);
    transform: translateY(-1px);
}

.preset-card .preset-name {
    font-weight: 600;
    color: var(--text-primary);
    font-size: 0.95rem;
    margin-bottom: 0.25rem;
}

.preset-card .preset-desc {
    color: var(--text-secondary);
    font-size: 0.8rem;
}

/* Filter section */
.filter-group {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 1rem;
    margin-bottom: 0.75rem;
}

.filter-controls {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1rem;
    padding: 0.5rem 0;
}

.filter-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 1rem;
    margin-top: 1rem;
}

.filter-item {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
}

.filter-label-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.filter-label {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--text-primary);
}

.filter-inputs {
    display: flex;
    gap: 0.5rem;
    align-items: center;
}

/* Streamlit element overrides */
div[data-testid="stMetricValue"] {
    font-family: 'Inter', sans-serif !important;
    font-weight: 700 !important;
}

/* Pagination */
.pagination-info {
    color: var(--text-secondary);
    font-size: 0.85rem;
    text-align: center;
    padding: 0.5rem;
}

/* Badge */
.badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
}

.badge-primary {
    background: var(--accent-glow);
    color: var(--accent-tertiary);
    border: 1px solid rgba(99, 102, 241, 0.3);
}

.badge-success {
    background: rgba(16, 185, 129, 0.1);
    color: var(--success);
    border: 1px solid rgba(16, 185, 129, 0.3);
}

.badge-warning {
    background: rgba(245, 158, 11, 0.1);
    color: var(--warning);
    border: 1px solid rgba(245, 158, 11, 0.3);
}

/* Watchlist indicator */
.watchlist-star {
    cursor: pointer;
    font-size: 1.2rem;
    transition: transform 0.2s;
}

.watchlist-star:hover {
    transform: scale(1.2);
}

/* Active filters badge */
.active-filters {
    background: var(--accent-glow);
    border: 1px solid rgba(99, 102, 241, 0.3);
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    margin-bottom: 1.5rem;
    color: var(--text-secondary);
    font-size: 0.8rem;
}

.active-filters strong {
    color: var(--accent-tertiary);
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 2px;
    background: var(--bg-secondary);
    border-radius: 10px;
    padding: 4px;
}

.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 500;
}

/* Button styling */
.stButton > button {
    border-radius: 8px !important;
    font-weight: 500 !important;
    font-family: 'Inter', sans-serif !important;
    transition: all 0.2s ease !important;
}

.stButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3) !important;
}

/* Download button */
.stDownloadButton > button {
    border-radius: 8px !important;
    font-weight: 500 !important;
}

/* Expander styling */
.streamlit-expanderHeader {
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    background: var(--bg-secondary) !important;
    border-radius: 8px !important;
}

/* Number input styling */
div[data-testid="stNumberInput"] input {
    border-radius: 8px !important;
}

/* Selectbox styling */
div[data-testid="stSelectbox"] > div > div {
    border-radius: 8px !important;
}

/* Text input */
div[data-testid="stTextInput"] input {
    border-radius: 8px !important;
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
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: var(--bg-primary);
}
::-webkit-scrollbar-thumb {
    background: var(--border-color);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--text-muted);
}

/* Toast notification */
.toast {
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: var(--bg-card);
    border: 1px solid var(--accent-primary);
    border-radius: 10px;
    padding: 0.75rem 1.25rem;
    color: var(--text-primary);
    font-size: 0.85rem;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
    z-index: 9999;
    animation: slideIn 0.3s ease;
}

@keyframes slideIn {
    from { transform: translateX(100%); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
}

/* Loading spinner override */
.stSpinner > div {
    border-top-color: var(--accent-primary) !important;
}
</style>
""",
    unsafe_allow_html=True,
)


# ── Initialize services (cached) ────────────────────────────────────
@st.cache_resource
def get_store() -> SQLiteStore:
    return SQLiteStore()


@st.cache_resource
def get_cache() -> LocalCache:
    return LocalCache()


def get_api_key() -> str:
    """Get API key from env or session state."""
    if FINNHUB_API_KEY:
        return FINNHUB_API_KEY
    return st.session_state.get("finnhub_api_key", "")


def _fmt_market_cap(val: float | None) -> str:
    """Format market cap in human-readable form."""
    if val is None:
        return "—"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}T"
    if val >= 1_000:
        return f"${val / 1_000:.1f}B"
    return f"${val:.0f}M"


def _fmt_pct(val: float | None) -> str:
    """Format a percentage value."""
    if val is None:
        return "—"
    return f"{val:.1f}%"


def _fmt_number(val: float | None, decimals: int = 2) -> str:
    """Format a generic number."""
    if val is None:
        return "—"
    return f"{val:,.{decimals}f}"


# ── Load universe + metrics (cached) ────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def load_full_dataset(api_key: str | None = None) -> pd.DataFrame:
    """Load symbols and fetch metrics for the entire universe with local-first logic."""
    from stonks.config import CACHE_DIR

    cache_file = CACHE_DIR / "universe_data_full.parquet"

    # 1. High-speed disk cache (TTL 1 hour for the merged parquet)
    if cache_file.exists():
        mtime = cache_file.stat().st_mtime
        if (time.time() - mtime) < 3600:
            try:
                df = pd.read_parquet(cache_file)
                if not df.empty:
                    logger.info("Loaded full dataset from disk cache")
                    return df
            except Exception as e:
                logger.warning("Failed to read parquet cache: %s", e)

    # 2. Local-First: Try building from SQLite metrics cache
    cache = LocalCache()
    loader = UniverseLoader(api_key=api_key or "DUMMY", cache=cache)
    provider = MetricsProvider(api_key=api_key or "DUMMY", cache=cache)

    try:
        # get_common_stocks handles its own cache internally
        symbols_df = loader.get_common_stocks()
    except Exception as e:
        logger.warning(f"Failed to load symbols: {e}")
        symbols_df = pd.DataFrame()

    if symbols_df.empty:
        # If no symbols and no API key, we are stuck
        if cache_file.exists():
            return pd.read_parquet(cache_file)
        return pd.DataFrame()

    # Sort
    symbols_df = symbols_df.sort_values("symbol")
    symbol_list = symbols_df["symbol"].tolist()

    # get_metrics_for_symbols with cache_only=True ensures we don't spam API
    # if the worker hasn't reached these symbols yet.
    metrics_df = provider.get_metrics_for_symbols(symbol_list, cache_only=True)

    if metrics_df.empty and not api_key:
        if cache_file.exists():
            return pd.read_parquet(cache_file)
        return symbols_df

    # Merge
    result = symbols_df.merge(metrics_df, on="symbol", how="left")

    # Clean up
    drop_cols = [
        c
        for c in result.columns
        if c.startswith("_") or c in ("fcf_raw", "revenue_raw")
    ]
    result = result.drop(
        columns=[c for c in drop_cols if c in result.columns], errors="ignore"
    )

    # Save to disk
    if not result.empty:
        try:
            result.to_parquet(cache_file)
        except Exception as e:
            logger.warning("Failed to save parquet cache: %s", e)

    return result


# ── Render functions ─────────────────────────────────────────────────


def render_header() -> None:
    """Render the hero header."""
    st.markdown(
        """
    <div class="hero-header">
        <h1>📈 Stonks Screener</h1>
        <div class="hero-subtitle">
            Screen stocks using fundamental metrics from Finnhub · Filter · Sort · Analyze
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def render_summary_cards(df: pd.DataFrame) -> None:
    """Render summary metric cards."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="label">Total Stocks</div>
            <div class="value">{len(df):,}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col2:
        avg_pe = df["pe_ratio"].median() if "pe_ratio" in df.columns else None
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="label">Median P/E</div>
            <div class="value">{_fmt_number(avg_pe)}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col3:
        avg_roe = df["roe_pct"].median() if "roe_pct" in df.columns else None
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="label">Median ROE</div>
            <div class="value">{_fmt_pct(avg_roe)}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )

    with col4:
        avg_div = (
            df["dividend_yield_pct"].median()
            if "dividend_yield_pct" in df.columns
            else None
        )
        st.markdown(
            f"""
        <div class="metric-card">
            <div class="label">Median Div Yield</div>
            <div class="value">{_fmt_pct(avg_div)}</div>
        </div>
        """,
            unsafe_allow_html=True,
        )


def render_sidebar_filters(df: pd.DataFrame, store: SQLiteStore) -> dict[str, Any]:
    """Render the sidebar filter builder and return active filters."""
    with st.sidebar:
        # ── API Key (if not set) ─────────────────────────────────
        if not get_api_key():
            with st.expander("🔑 API Key (Limited Mode)", expanded=False):
                st.info(
                    "Operating in **Local-First mode**. Enter a Finnhub API key to enable live enrichment and real-time data fetching."
                )
                api_key_input = st.text_input(
                    "Finnhub API Key",
                    type="password",
                    help="Get a free key at https://finnhub.io",
                    key="api_key_input",
                )
                if api_key_input:
                    st.session_state["finnhub_api_key"] = api_key_input
                    st.rerun()

        # ── Logo / branding ──────────────────────────────────────
        st.markdown(
            """
        <div style="text-align: center; padding: 0.5rem 0 1rem 0;">
            <div style="font-size: 1.5rem; font-weight: 800;
                        background: linear-gradient(135deg, #6366f1, #a78bfa);
                        -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                🎯 Filters
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # ── Search ───────────────────────────────────────────────
        search_query = st.text_input(
            "🔍 Search",
            value=st.session_state.get("search_query", ""),
            placeholder="Symbol or company name...",
            key="search_input",
        )
        st.session_state["search_query"] = search_query

        st.divider()

        # ── Popular Screens ──────────────────────────────────────
        with st.expander("🌟 Popular Screens", expanded=False):
            for preset in POPULAR_SCREENS:
                col_a, col_b = st.columns([5, 1])
                with col_a:
                    st.markdown(f"**{preset['name']}**")
                    st.caption(preset["description"])
                with col_b:
                    if st.button(
                        "▶", key=f"preset_{preset['name']}", help="Apply this screen"
                    ):
                        st.session_state["active_filters"] = preset["filters"]
                        st.session_state["view_preset"] = preset.get(
                            "view_preset", "Overview"
                        )
                        if preset.get("sort_column"):
                            st.session_state["sort_column"] = preset["sort_column"]
                            st.session_state["sort_ascending"] = preset.get(
                                "sort_ascending", False
                            )
                        st.session_state["current_page"] = 1
                        st.rerun()

        # ── Saved Screens ────────────────────────────────────────
        with st.expander("💾 Saved Screens", expanded=False):
            saved = store.list_screens()
            if saved:
                for screen in saved:
                    col_a, col_b, col_c = st.columns([4, 1, 1])
                    with col_a:
                        st.markdown(f"**{screen['name']}**")
                    with col_b:
                        if st.button(
                            "▶", key=f"load_screen_{screen['name']}", help="Load"
                        ):
                            st.session_state["active_filters"] = screen["filters"]
                            st.session_state["view_preset"] = screen.get(
                                "view_preset", "Overview"
                            )
                            if screen.get("sort_column"):
                                st.session_state["sort_column"] = screen["sort_column"]
                                st.session_state["sort_ascending"] = screen.get(
                                    "sort_ascending", True
                                )
                            st.session_state["current_page"] = 1
                            st.rerun()
                    with col_c:
                        if st.button(
                            "🗑", key=f"del_screen_{screen['name']}", help="Delete"
                        ):
                            store.delete_screen(screen["name"])
                            st.rerun()
            else:
                st.caption("No saved screens yet.")

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
                    current_filters = st.session_state.get("active_filters", {})
                    view_preset = st.session_state.get("view_preset", "Overview")
                    sort_col = st.session_state.get("sort_column")
                    sort_asc = st.session_state.get("sort_ascending", True)
                    store.save_screen(
                        save_name, current_filters, view_preset, sort_col, sort_asc
                    )
                    st.toast(f"✅ Screen '{save_name}' saved!", icon="💾")
                else:
                    st.warning("Please enter a name.")

        # ── Data management ──────────────────────────────────────
        st.divider()
        with st.expander("⚙️ Settings", expanded=False):
            if st.button(
                "🧹 Clear All Cache", key="reload_data", use_container_width=True
            ):
                st.cache_data.clear()
                cache = get_cache()
                cache.clear()
                st.rerun()

    return st.session_state.get("active_filters", {})


def render_top_filters(df: pd.DataFrame) -> dict[str, Any]:
    """Render numeric and category filters in a grid above the stock view."""
    filters = st.session_state.get("active_filters", {}).copy()

    with st.expander("🎯 Filters", expanded=False):
        # ── Filter Top Bar ───────────────────────────────────────
        ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1, 2, 1])

        with ctrl_col1:
            # Dropdown to add a new filter
            available_numeric = [c for c in NUMERIC_FILTER_COLUMNS if c in df.columns]
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

        for i, col in enumerate(ENUM_FILTER_COLUMNS):
            if col not in df.columns:
                continue
            display_name = COLUMN_DISPLAY_NAMES.get(col, col)
            unique_vals = sorted(df[col].dropna().unique().tolist())
            if not unique_vals:
                continue

            with cat_cols[i % 4]:
                selected = st.multiselect(
                    display_name,
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
        active_cols = sorted([c for c in filters.keys() if c in NUMERIC_FILTER_COLUMNS])

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
            st.session_state["current_page"] = 1
            st.rerun()

    return filters


def render_screener_table(
    df: pd.DataFrame,
    engine: ScreenerEngine,
    store: SQLiteStore,
) -> None:
    """Render the main screener table with controls."""

    # ── View preset selector ─────────────────────────────────────
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
        available_cols = [c for c in df.columns if c in COLUMN_DISPLAY_NAMES]
        sort_options = ["None"] + [
            COLUMN_DISPLAY_NAMES.get(c, c) for c in available_cols
        ]
        sort_keys = ["None"] + available_cols

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

    # ── Run screen ───────────────────────────────────────────────
    active_filters = st.session_state.get("active_filters", {})
    search_query = st.session_state.get("search_query", "")
    current_page = st.session_state.get("current_page", 1)

    page_df, total_pages, total_matching = engine.run_screen(
        filters=active_filters,
        search_query=search_query,
        sort_column=sort_column,
        sort_ascending=st.session_state.get("sort_ascending", True),
        page=current_page,
        page_size=page_size,
    )

    if total_matching == 0 and (active_filters or search_query):
        st.warning("⚠️ **No stocks match your current filters.**")

    # ── Active filters info bar ──────────────────────────────────
    if active_filters or search_query:
        filter_parts = []

        # Human-readable filter descriptions
        for col, spec in active_filters.items():
            display = COLUMN_DISPLAY_NAMES.get(col, col)
            parts = []
            if "min" in spec:
                parts.append(f"≥ {spec['min']}")
            if "max" in spec:
                parts.append(f"≤ {spec['max']}")
            if "values" in spec:
                parts.append(f"∈ {spec['values']}")

            if parts:
                filter_parts.append(f"**{display}**: {', '.join(parts)}")

        # Add search query if present
        if search_query:
            filter_parts.append(f'🔍 **Search**: "{search_query}"')

        # Render the bar
        if filter_parts:
            # Use raw HTML tags for reliable rendering inside the div
            html_parts = []
            for p in filter_parts:
                # Replace ** with <strong> for the parts
                html_parts.append(
                    p.replace("**", "<strong>").replace("**", "</strong>")
                )

            st.markdown(
                f"""<div class="active-filters">
                🎯 <strong>Active filters:</strong> {" · ".join(html_parts)}
                &nbsp;|&nbsp; Matching: <strong>{total_matching:,}</strong> stocks
                </div>""",
                unsafe_allow_html=True,
            )

    # ── Select visible columns ───────────────────────────────────
    preset_cols = VIEW_PRESETS.get(view_preset, [])
    if preset_cols:
        visible_cols = [c for c in preset_cols if c in page_df.columns]
    else:
        visible_cols = [c for c in page_df.columns if not c.startswith("_")]

    if not visible_cols:
        visible_cols = list(page_df.columns)

    display_df = page_df[visible_cols].copy()

    # ── Watchlist highlighting ───────────────────────────────────
    watchlist_symbols = set(store.get_watchlist_symbols())

    if "symbol" in display_df.columns:
        display_df["symbol"] = display_df["symbol"].apply(
            lambda x: f"⭐ {x}" if x in watchlist_symbols else x
        )

    # Rename columns for display
    rename_map = {c: COLUMN_DISPLAY_NAMES.get(c, c) for c in visible_cols}
    display_df = display_df.rename(columns=rename_map)

    # ── Format numeric columns ───────────────────────────────────
    for col in display_df.columns:
        if col == "Market Cap":
            display_df[col] = display_df[col].apply(_fmt_market_cap)
        elif "%" in col:
            display_df[col] = display_df[col].apply(_fmt_pct)
        elif col in (
            "P/E",
            "P/B",
            "P/S",
            "PEG",
            "EV/EBITDA",
            "Current Ratio",
            "D/E",
            "Beta",
            "Total D/E",
            "LT D/E",
        ):
            display_df[col] = display_df[col].apply(lambda x: _fmt_number(x, 2))
        elif col in (
            "Price",
            "52W High",
            "52W Low",
            "FCF/Share",
            "Rev/Share",
            "BV/Share",
            "TBV/Share",
            "EPS (TTM)",
        ):
            display_df[col] = display_df[col].apply(lambda x: _fmt_number(x, 2))

    # ── Render table ─────────────────────────────────────────────
    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        height=min(35 * len(display_df) + 38, 800),
    )

    # ── Pagination controls ──────────────────────────────────────
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

    # ── Download CSV ─────────────────────────────────────────────
    # Get full filtered data (not just current page) for download
    full_filtered_df = (
        engine.apply_filters(active_filters) if active_filters else engine.raw_df
    )
    if search_query:
        full_filtered_df = engine.search(full_filtered_df, search_query)

    csv_data = full_filtered_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=f"📥 Download CSV ({len(full_filtered_df):,} rows)",
        data=csv_data,
        file_name=f"stonks_screener_{time.strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        key="download_csv",
    )


def render_watchlist_tab(df: pd.DataFrame, store: SQLiteStore) -> None:
    """Render the watchlist management tab."""
    st.markdown(
        '<div class="section-header">⭐ Watchlist</div>', unsafe_allow_html=True
    )

    # Add to watchlist
    col_add, col_btn = st.columns([3, 1])
    with col_add:
        symbols_in_df = sorted(df["symbol"].tolist()) if "symbol" in df.columns else []
        add_symbol = st.selectbox(
            "Add to watchlist",
            options=[""] + symbols_in_df,
            key="watchlist_add_symbol",
            label_visibility="collapsed",
            placeholder="Select a symbol to add...",
        )
    with col_btn:
        if st.button(
            "⭐ Add", key="watchlist_add_btn", use_container_width=True, type="primary"
        ):
            if add_symbol:
                store.add_to_watchlist(add_symbol)
                st.toast(f"⭐ Added {add_symbol} to watchlist!", icon="✅")
                time.sleep(0.5)
                st.rerun()

    st.divider()

    # Display watchlist
    watchlist = store.get_watchlist()
    if not watchlist:
        st.info(
            "Your watchlist is empty. Add stocks using the selector above or from the screener."
        )
        return

    watchlist_symbols = [item["symbol"] for item in watchlist]

    # Get data for watchlist symbols
    watchlist_df = (
        df[df["symbol"].isin(watchlist_symbols)].copy()
        if "symbol" in df.columns
        else pd.DataFrame()
    )

    if not watchlist_df.empty:
        # Show watchlist with key metrics
        view_cols = [
            "symbol",
            "description",
            "market_cap",
            "pe_ratio",
            "roe_pct",
            "dividend_yield_pct",
            "price",
            "beta",
        ]
        view_cols = [c for c in view_cols if c in watchlist_df.columns]
        display_wl = watchlist_df[view_cols].copy()

        rename_map = {c: COLUMN_DISPLAY_NAMES.get(c, c) for c in view_cols}
        display_wl = display_wl.rename(columns=rename_map)

        # Format
        if "Market Cap" in display_wl.columns:
            display_wl["Market Cap"] = display_wl["Market Cap"].apply(_fmt_market_cap)
        for col in display_wl.columns:
            if "%" in col:
                display_wl[col] = display_wl[col].apply(_fmt_pct)
            elif col in ("P/E", "Beta"):
                display_wl[col] = display_wl[col].apply(lambda x: _fmt_number(x, 2))

        st.dataframe(display_wl, width="stretch", hide_index=True)

        # Download watchlist
        csv = watchlist_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label=f"📥 Download Watchlist CSV ({len(watchlist_df)} stocks)",
            data=csv,
            file_name=f"stonks_watchlist_{time.strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            key="download_watchlist",
        )

    # Remove from watchlist
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
    candles = sync_info["candles_count"]
    failed = sync_info["failed_count"]
    total = sync_info["total_symbols"]
    completion = (success / max(1, total)) * 100
    candle_completion = (candles / max(1, total)) * 100

    st.markdown(
        """
        <style>
        .hud-card {
            background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.8) 100%);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
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
            padding: 2px 8px;
            border-radius: 9999px;
            background: rgba(34, 197, 94, 0.2);
            color: #4ade80;
            border: 1px solid rgba(34, 197, 94, 0.3);
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
            background: linear-gradient(90deg, #3b82f6 0%, #2dd4bf 100%);
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
                        <div class="metric-value">{candle_completion:.1f}%</div>
                        <div class="metric-label">Historical Data</div>
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


def main() -> None:
    """Main Streamlit app entry point."""
    render_header()

    store = get_store()

    # Check API key
    api_key = get_api_key()
    if not api_key:
        st.sidebar.markdown("### 🔑 API Key Required")
        key_input = st.sidebar.text_input(
            "Finnhub API Key",
            type="password",
            help="Get a free key at https://finnhub.io",
            key="api_key_sidebar",
        )
        if key_input:
            st.session_state["finnhub_api_key"] = key_input
            st.rerun()

        # Show placeholder
        st.markdown(
            """
        <div style="text-align: center; padding: 4rem 2rem;">
            <div style="font-size: 4rem; margin-bottom: 1rem;">🔑</div>
            <h2 style="color: #f1f5f9; margin-bottom: 0.5rem;">Welcome to Stonks Screener</h2>
            <p style="color: #94a3b8; max-width: 500px; margin: 0 auto;">
                Enter your <a href="https://finnhub.io" target="_blank" style="color: #6366f1;">Finnhub</a>
                API key in the sidebar to get started. The free tier works great!
            </p>
        </div>
        """,
            unsafe_allow_html=True,
        )
        return

    # Initialize session state
    if "active_filters" not in st.session_state:
        # Load default screen: The Quality Screen
        from stonks.presets import POPULAR_SCREENS

        quality_screen = next(
            (s for s in POPULAR_SCREENS if "Quality Screen" in s["name"]),
            POPULAR_SCREENS[0],
        )
        st.session_state["active_filters"] = quality_screen["filters"].copy()
        st.session_state["view_preset"] = quality_screen["view_preset"]
        st.session_state["sort_column"] = quality_screen["sort_column"]
        st.session_state["sort_ascending"] = quality_screen["sort_ascending"]
        st.session_state["current_page"] = 1

    if "current_page" not in st.session_state:
        st.session_state["current_page"] = 1
    if "view_preset" not in st.session_state:
        st.session_state["view_preset"] = "Overview"
    if "sort_column" not in st.session_state:
        st.session_state["sort_column"] = None
    if "sort_ascending" not in st.session_state:
        st.session_state["sort_ascending"] = True
    if "page_size" not in st.session_state:
        st.session_state["page_size"] = DEFAULT_PAGE_SIZE

    # Load data

    # UI for sync status
    sync_info = store.get_last_sync_info()
    render_pipeline_hud(sync_info)

    df = pd.DataFrame()
    try:
        # Try local-first loading
        df = load_full_dataset(api_key)
    except Exception as e:
        err_msg = str(e)
        if ("401" in err_msg or "Invalid API key" in err_msg) and api_key:
            st.error(
                "❌ **Invalid API key.** Please check your Finnhub API key and try again."
            )
            st.session_state.pop("finnhub_api_key", None)
            st.cache_data.clear()
            if st.button("🔑 Enter a new API key", key="retry_api_key"):
                st.rerun()
            return
        elif "429" in err_msg or "rate" in err_msg.lower():
            st.toast("⏳ Rate limit exceeded. Waiting a moment...", icon="⚠️")
            time.sleep(1)
            st.rerun()
            return
        else:
            st.error(f"❌ Failed to load data: {e}")
            if st.button("🔄 Retry", key="retry_generic"):
                st.cache_data.clear()
                st.rerun()
            return

    if df.empty:
        st.error("❌ No data loaded. Check your API key and try again.")
        col_retry1, col_retry2 = st.columns(2)
        with col_retry1:
            if st.button("🔄 Retry", key="retry_empty"):
                st.cache_data.clear()
                st.rerun()
        with col_retry2:
            if st.button("🔑 Change API Key", key="change_key_empty"):
                st.session_state.pop("finnhub_api_key", None)
                st.cache_data.clear()
                st.rerun()
        return

    # Render sidebar filters (also handles Popular/Saved screens)
    render_sidebar_filters(df, store)

    # Apply all filters
    engine = ScreenerEngine(df)

    # Summary cards
    render_summary_cards(df)

    # Main content tabs
    tab_screener, tab_watchlist = st.tabs(["📊 Screener", "⭐ Watchlist"])

    with tab_screener:
        # Render the new top-level filters grid
        render_top_filters(df)

        # engine is already initialized, but we need to pass the CURRENT filtered DF to the table renderer
        # or let the table renderer do its own filtering/search
        render_screener_table(df, engine, store)

    with tab_watchlist:
        render_watchlist_tab(df, store)

    # Footer
    st.markdown(
        """
    <div class="app-footer">
        Stonks Screener v0.1.0 · Data from <a href="https://finnhub.io" style="color: #6366f1;">Finnhub</a> ·
        Built with <a href="https://streamlit.io" style="color: #6366f1;">Streamlit</a>
    </div>
    """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
