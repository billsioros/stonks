"""Application configuration and constants."""

from __future__ import annotations

import os
from pathlib import Path

# ── Finnhub ──────────────────────────────────────────────────────────
FINNHUB_API_KEY: str = os.environ.get("FINNHUB_API_KEY", "")

# ── Paths ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "stonks.db"

# Ensure dirs exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Cache TTL (seconds) ─────────────────────────────────────────────
SYMBOLS_CACHE_TTL: int = 86_400  # 24 hours
METRICS_CACHE_TTL: int = 86_400  # 24 hours

# ── Rate limiting ────────────────────────────────────────────────────
FINNHUB_RATE_LIMIT_CALLS: int = 30  # free tier: 30 calls/sec
FINNHUB_RATE_LIMIT_WINDOW: float = 1.0  # seconds

# ── Default universe ────────────────────────────────────────────────
DEFAULT_EXCHANGE: str = "US"

# ── Screener defaults ───────────────────────────────────────────────
DEFAULT_PAGE_SIZE: int = 25
PAGE_SIZE_OPTIONS: list[int] = [10, 25, 50, 100]

# ── Column display names ────────────────────────────────────────────
COLUMN_DISPLAY_NAMES: dict[str, str] = {
    "symbol": "Symbol",
    "description": "Company",
    "exchange": "Exchange",
    "type": "Type",
    "mic": "MIC",
    "currency": "Currency",
    "market_cap": "Market Cap",
    "pe_ratio": "P/E",
    "pb_ratio": "P/B",
    "ps_ratio": "P/S",
    "dividend_yield_pct": "Div Yield %",
    "gross_margin_pct": "Gross Margin %",
    "operating_margin_pct": "Op Margin %",
    "net_margin_pct": "Net Margin %",
    "roa_pct": "ROA %",
    "roe_pct": "ROE %",
    "roic_pct": "ROIC %",
    "current_ratio": "Current Ratio",
    "debt_to_equity": "D/E",
    "fcf_margin_pct": "FCF Margin %",
    "revenue_growth_5y_pct": "Rev Growth 5Y %",
    "eps_growth_5y_pct": "EPS Growth 5Y %",
    "beta": "Beta",
    "week_52_high": "52W High",
    "week_52_low": "52W Low",
    "price": "Price",
    "peg_ratio": "PEG",
    "ev_to_ebitda": "EV/EBITDA",
    "free_cash_flow_per_share": "FCF/Share",
    "revenue_per_share": "Rev/Share",
    "book_value_per_share": "BV/Share",
    "tangible_book_value_per_share": "TBV/Share",
    "total_debt_to_total_equity": "Total D/E",
    "long_term_debt_to_equity": "LT D/E",
    "inventory_turnover": "Inv Turnover",
    "receivables_turnover": "Recv Turnover",
    "asset_turnover": "Asset Turnover",
    "eps_ttm": "EPS (TTM)",
    "eps_growth_3y_pct": "EPS Growth 3Y %",
    "revenue_growth_3y_pct": "Rev Growth 3Y %",
}

# ── View presets ─────────────────────────────────────────────────────
VIEW_PRESETS: dict[str, list[str]] = {
    "Overview": [
        "symbol", "description", "exchange", "market_cap", "price",
        "pe_ratio", "dividend_yield_pct", "beta",
    ],
    "Valuation": [
        "symbol", "description", "market_cap", "pe_ratio", "pb_ratio",
        "ps_ratio", "peg_ratio", "ev_to_ebitda",
    ],
    "Profitability": [
        "symbol", "description", "gross_margin_pct", "operating_margin_pct",
        "net_margin_pct", "roa_pct", "roe_pct", "roic_pct",
    ],
    "Growth": [
        "symbol", "description", "revenue_growth_5y_pct", "revenue_growth_3y_pct",
        "eps_growth_5y_pct", "eps_growth_3y_pct", "market_cap",
    ],
    "Financial Health": [
        "symbol", "description", "current_ratio", "debt_to_equity",
        "long_term_debt_to_equity", "fcf_margin_pct", "free_cash_flow_per_share",
    ],
    "All Columns": [],  # empty means show all
}

# ── Numeric filter columns ──────────────────────────────────────────
NUMERIC_FILTER_COLUMNS: list[str] = [
    "market_cap", "pe_ratio", "pb_ratio", "ps_ratio", "peg_ratio",
    "ev_to_ebitda", "dividend_yield_pct", "gross_margin_pct",
    "operating_margin_pct", "net_margin_pct", "roa_pct", "roe_pct",
    "roic_pct", "current_ratio", "debt_to_equity", "fcf_margin_pct",
    "revenue_growth_5y_pct", "eps_growth_5y_pct", "beta", "price",
    "revenue_growth_3y_pct", "eps_growth_3y_pct",
    "free_cash_flow_per_share", "revenue_per_share",
    "book_value_per_share", "long_term_debt_to_equity",
    "asset_turnover", "eps_ttm",
]

# ── Enum filter columns ─────────────────────────────────────────────
ENUM_FILTER_COLUMNS: list[str] = ["exchange", "type", "currency", "mic"]
