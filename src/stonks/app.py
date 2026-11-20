"""Stonks — Streamlit Stock Screener App.

Run with: streamlit run src/stonks/app.py
"""

import logging
import math
import time
from datetime import datetime
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import streamlit as st

from stonks.config import (
    COLUMN_DISPLAY_NAMES,
    DEFAULT_PAGE_SIZE,
    ENUM_FILTER_COLUMNS,
    NUMERIC_FILTER_COLUMNS,
    PAGE_SIZE_OPTIONS,
    VIEW_PRESETS,
)
from stonks.presets import POPULAR_SCREENS
from stonks.store import SQLiteStore

logger = logging.getLogger(__name__)

# ── Page configuration ──────────────────────────────────────────────
st.set_page_config(
    page_title="Stonks — Stock Screener",
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
    font-size: 1.6rem;
    border-radius: 14px;
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
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

.sk-pulse {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.35rem 0.85rem;
    border-radius: 999px;
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    color: var(--text-primary);
    font-size: 0.82rem;
    font-weight: 600;
}

.sk-meta p {
    margin: 0.55rem 0 0;
    color: var(--text-secondary);
    font-size: 0.85rem;
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

/* Active filter summary */
.active-filters {
    background: var(--accent-soft);
    border: 1px solid var(--accent-border);
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    margin-bottom: 1.5rem;
    color: var(--text-secondary);
    font-size: 0.8rem;
}

.active-filters strong {
    color: var(--text-primary);
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

/* Data editor/table */
[data-testid="stDataFrame"] {
    border: 1px solid var(--border-color);
    border-radius: 12px;
    overflow: hidden;
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

/* Expander */
.streamlit-expanderHeader {
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    background: var(--bg-secondary) !important;
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


def _is_missing(val: object) -> bool:
    """True for None or NaN (pandas turns NULLs into NaN in the display frame)."""
    return val is None or (isinstance(val, float) and math.isnan(val))


def _fmt_flag(val: object) -> str:
    """Render a stored 1/0 flag: ✓ in the list, ✗ not, — unknown."""
    if _is_missing(val):
        return "—"
    return "✓" if val else "✗"


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


def render_header() -> None:
    """Render the masthead: brand on the left, data source on the right."""
    st.markdown(
        """
    <div class="sk-head">
        <div class="sk-brand">
            <div class="sk-mark">📈</div>
            <h1>Stonks</h1>
        </div>
        <div class="sk-meta">
            <span class="sk-pulse">● Auto-sync</span>
            <p>Fundamental screener · data from StockAnalysis.com</p>
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def render_sidebar_filters() -> dict[str, Any]:
    """Render the sidebar filter builder without requiring df."""
    with st.sidebar:
        # ── Logo / branding ──────────────────────────────────────
        st.markdown(
            """
        <div style="text-align: center; padding: 0.5rem 0 1rem 0;">
            <div style="font-size: 1.5rem; font-weight: 700; color: #f8fafc;">
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
        store = get_store()
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
            st.info("Cache is managed by the worker.")

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
            st.session_state["current_page"] = 1
            st.rerun()

    return filters  # type: ignore[no-any-return]


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

    page_rows, total_pages, total_matching = store.get_stocks(
        filters=active_filters,
        search_query=search_query,
        sort_column=sort_column,
        sort_ascending=st.session_state.get("sort_ascending", True),
        page=current_page,
        page_size=page_size,
    )

    if total_matching == 0 and (active_filters or search_query):
        st.warning("⚠️ **No stocks match your current filters.**")

    if active_filters or search_query:
        filter_parts = []

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

        if search_query:
            filter_parts.append(f'🔍 **Search**: "{search_query}"')

        if filter_parts:
            html_parts = []
            for p in filter_parts:
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

    for col in display_df.columns:
        if col == "Largest HF Buy":
            display_df[col] = display_df[col].apply(_fmt_flag)
        elif col == "Market Cap":
            display_df[col] = display_df[col].apply(_fmt_market_cap)
        elif "%" in col or "Upside" in col or "Short" in col:
            display_df[col] = display_df[col].apply(_fmt_pct)
        elif col in (
            "Pe ratio",
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
            display_df[col] = display_df[col].apply(lambda x: _fmt_number(x, 2))

    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        height=min(35 * len(display_df) + 38, 800),
    )

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


def render_watchlist_tab() -> None:
    """Render the watchlist management tab."""
    store = get_store()
    st.markdown(
        '<div class="section-header">⭐ Watchlist</div>', unsafe_allow_html=True
    )

    all_symbols = store.get_unique_values("symbol")
    if not all_symbols:
        all_symbols = []

    col_add, col_btn = st.columns([3, 1])
    with col_add:
        add_symbol = st.selectbox(
            "Add to watchlist",
            options=[""] + sorted(all_symbols),
            key="watchlist_add_symbol",
            label_visibility="collapsed",
            placeholder="Select a symbol to add...",
        )
    with col_btn:
        if (
            st.button(
                "⭐ Add",
                key="watchlist_add_btn",
                use_container_width=True,
                type="primary",
            )
            and add_symbol
        ):
            store.add_to_watchlist(add_symbol)
            st.toast(f"⭐ Added {add_symbol} to watchlist!", icon="✅")
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

        if "Market Cap" in display_wl.columns:
            display_wl["Market Cap"] = display_wl["Market Cap"].apply(_fmt_market_cap)
        for col in display_wl.columns:
            if "%" in col:
                display_wl[col] = display_wl[col].apply(_fmt_pct)
            elif col in ("P/E", "Beta", "DCF Fair Value", "Lynch Fair Value"):
                display_wl[col] = display_wl[col].apply(lambda x: _fmt_number(x, 2))

        st.dataframe(display_wl, width="stretch", hide_index=True)

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


def main() -> None:
    """Main Streamlit app entry point."""
    render_header()
    render_sidebar_filters()

    store = get_store()
    sync_info = store.get_last_sync_info()
    render_pipeline_hud(sync_info)

    # Initialize session state
    if "active_filters" not in st.session_state:
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

    # Main content tabs
    tab_screener, tab_watchlist = st.tabs(["📊 Screener", "⭐ Watchlist"])

    with tab_screener:
        # Render the new top-level filters grid
        render_top_filters()

        # engine is already initialized, but we need to pass the CURRENT filtered DF to the table renderer
        # or let the table renderer do its own filtering/search
        render_screener_table()

    with tab_watchlist:
        render_watchlist_tab()

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
