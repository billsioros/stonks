"""Application configuration and constants."""

from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "stonks.db"

# Ensure dirs exist
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── Worker ───────────────────────────────────────────────────────────
# The worker refreshes the full screener dataset on this interval.
WORKER_INTERVAL_MINUTES = 15
# A sync counts as live for two worker intervals: one missed run is tolerated,
# two consecutive misses mean the worker is no longer keeping up.
SYNC_ACTIVE_WINDOW_MINUTES = 2 * WORKER_INTERVAL_MINUTES

# ── Screener defaults ───────────────────────────────────────────────
DEFAULT_PAGE_SIZE: int = 25
PAGE_SIZE_OPTIONS: list[int] = [10, 25, 50, 100]
# Keep the screener grid inside a typical browser viewport; larger pages scroll
# inside the table instead of pushing the footer off screen.
SCREENER_TABLE_MAX_HEIGHT: int = 480

# ── Column display names ────────────────────────────────────────────
# Columns computed for the displayed page rather than read from the stocks
# table: they must stay out of SQL filters, sorting and schema checks.
VIRTUAL_COLUMNS: frozenset[str] = frozenset({"portfolio_correlation"})

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
    "price": "Stock Price",
    "peg_ratio": "PEG",
    "ev_to_ebitda": "EV/EBITDA",
    "free_cash_flow_per_share": "FCF/Share",
    "revenue_per_share": "Rev/Share",
    "book_value_per_share": "BV/Share",
    "tangible_book_value_per_share": "TBV/Share",
    "long_term_debt_to_equity": "LT D/E",
    "asset_turnover": "Asset Turnover",
    "eps_ttm": "EPS (TTM)",
    "eps_growth_3y_pct": "EPS Growth 3Y %",
    "revenue_growth_3y_pct": "Rev Growth 3Y %",
    "net_income": "Net Income",
    "free_cash_flow": "Free Cash Flow",
    "fcf_growth_5y_pct": "FCF Growth 5Y %",
    "net_income_growth_5y_pct": "Net Income Growth 5Y %",
    "return_cagr_5y_pct": "Return CAGR 5Y %",
    "return_cagr_10y_pct": "Return CAGR 10Y %",
    "return_cagr_15y_pct": "Return CAGR 15Y %",
    "roa_5y_avg_pct": "ROA (5Y) %",
    "roe_5y_avg_pct": "ROE (5Y) %",
    "roic_5y_avg_pct": "ROIC (5Y) %",
    "shares_insiders_pct": "Shares Insiders (Ratio)",
    "shares_insiders_percent": "Insider Ownership %",
    "cyclical_peak_risk": "Cyclical Peak Risk",
    "valuation_triangulation": "Model Agreement",
    "valuation_upside_capped_pct": "Avg Upside %",
    "industry": "Industry",
    "short_pct": "Short % Shares",
    "rating": "Rating",
    "pt_upside_pct": "PT Upside",
    "dcf_fair_value": "DCF Fair Value",
    "dcf_upside_pct": "DCF Upside %",
    "lynch_fair_value": "Lynch Fair Value",
    "lynch_upside_pct": "Lynch Upside %",
    "hedge_fund_buys": "13F Whale",
    "portfolio_correlation": "Portfolio Correlation",
}

# ── Column help texts ──────────────────────────────────────────────
# One plain-language line per displayed column: what it measures and, wherever
# a reader could misread the number, its unit. Shown in the screener's column
# guide so no abbreviation needs outside knowledge.
COLUMN_HELP: dict[str, str] = {
    "symbol": "Ticker symbol used to look the stock up.",
    "description": "Company name and short business summary.",
    "exchange": "Exchange the stock trades on.",
    "type": "Security type (stock, ETF, and so on).",
    "mic": "Market identifier code of the primary listing venue.",
    "currency": "Currency the price and statements are reported in.",
    "market_cap": "Share price times shares outstanding.",
    "pe_ratio": "Share price divided by trailing twelve-month earnings per share.",
    "pb_ratio": "Share price divided by book value per share.",
    "ps_ratio": "Share price divided by revenue per share.",
    "dividend_yield_pct": "Annual dividend divided by price, in percent.",
    "gross_margin_pct": "Gross profit divided by revenue, in percent.",
    "operating_margin_pct": "Operating income divided by revenue, in percent.",
    "net_margin_pct": "Net income divided by revenue, in percent.",
    "roa_pct": "Net income divided by total assets, in percent.",
    "roe_pct": "Net income divided by shareholders' equity, in percent.",
    "roic_pct": "Operating profit after tax divided by invested capital, in percent.",
    "current_ratio": (
        "Current assets ÷ current liabilities; below 1 means short-term bills "
        "exceed short-term assets."
    ),
    "debt_to_equity": "Total debt divided by shareholders' equity.",
    "fcf_margin_pct": "Free cash flow ÷ revenue, in percent.",
    "revenue_growth_5y_pct": "Compound annual revenue growth over five years, in percent.",
    "eps_growth_5y_pct": "Compound annual earnings-per-share growth over five years.",
    "beta": "Price volatility versus the market; 1.0 moves with the market.",
    "week_52_high": "Highest traded price in the last 52 weeks.",
    "week_52_low": "Lowest traded price in the last 52 weeks.",
    "price": "Latest traded share price.",
    "peg_ratio": "P/E divided by expected earnings growth; under 1 is cheap on this measure.",
    "ev_to_ebitda": "Enterprise value divided by EBITDA; lower is cheaper.",
    "free_cash_flow_per_share": "Free cash flow divided by shares outstanding.",
    "revenue_per_share": "Revenue divided by shares outstanding.",
    "book_value_per_share": "Shareholders' equity divided by shares outstanding.",
    "tangible_book_value_per_share": "Book value less intangible assets, per share.",
    "long_term_debt_to_equity": "Long-term debt divided by shareholders' equity.",
    "asset_turnover": "Revenue divided by total assets; sales per unit of assets.",
    "eps_ttm": "Earnings per share over the trailing twelve months.",
    "eps_growth_3y_pct": "Compound annual earnings-per-share growth over three years.",
    "revenue_growth_3y_pct": "Compound annual revenue growth over three years.",
    "net_income": "Profit after tax for the trailing period, in reporting currency.",
    "free_cash_flow": "Operating cash flow less capital spending, in reporting currency.",
    "fcf_growth_5y_pct": "Compound annual free-cash-flow growth over five years.",
    "net_income_growth_5y_pct": "Compound annual net-income growth over five years.",
    "return_cagr_5y_pct": "Annualized total shareholder return over five years.",
    "return_cagr_10y_pct": "Annualized total shareholder return over ten years.",
    "return_cagr_15y_pct": "Annualized total shareholder return over fifteen years.",
    "roa_5y_avg_pct": "Five-year average return on assets.",
    "roe_5y_avg_pct": "Five-year average return on equity.",
    "roic_5y_avg_pct": "Five-year average return on invested capital; the best single quality gauge.",
    "shares_insiders_pct": "Insiders' stake as a fraction, where 0.05 means 5%.",
    "shares_insiders_percent": "Insiders' stake as a percentage, where 5.0 means 5%.",
    "cyclical_peak_risk": "1 when a cyclical stock screens cheap on peak earnings.",
    "valuation_triangulation": (
        "Verdict on how many valuation signals agree: Strong Consensus, Moderate "
        "Value, Model Divergence / Outlier, Cyclical Distorted, or Unrated / "
        "Insufficient Data."
    ),
    "valuation_upside_capped_pct": (
        "Average model upside per stock, capped at 150% so one outlier cannot "
        "dominate a ranking."
    ),
    "industry": "Provider industry classification.",
    "short_pct": "Shares sold short as a percentage of the float.",
    "rating": "Analyst consensus rating.",
    "pt_upside_pct": "Median analyst price target versus today's price, in percent.",
    "dcf_fair_value": "Vendor discounted-cash-flow value per share.",
    "dcf_upside_pct": "DCF fair value versus today's price, in percent.",
    "lynch_fair_value": "Growth-adjusted fair value per share, in the Lynch style.",
    "lynch_upside_pct": "Lynch fair value versus today's price, in percent.",
    "hedge_fund_buys": (
        "🐋 when the stock is in HedgeFollow's largest hedge-fund buys, ✗ when "
        "it is in the feed but not on that list, and — when HedgeFollow has no "
        "data. 13F filings lag up to 45 days and crowding is not a signal on "
        "its own."
    ),
    "portfolio_correlation": (
        "Pearson correlation of monthly adjusted returns over the last 36 months "
        "against the weighted portfolio; at least 12 months must overlap. "
        "Returns use each instrument's native currency (VUAA is proxied by VOO). "
        "⚠️ marks the 0.70 high-correlation threshold; blank means insufficient "
        "history."
    ),
}

# ── View presets ─────────────────────────────────────────────────────
VIEW_PRESETS: dict[str, list[str]] = {
    "Overview": [
        "symbol",
        "description",
        "exchange",
        "market_cap",
        "price",
        "pe_ratio",
        "dividend_yield_pct",
        "beta",
        "dcf_fair_value",
        "dcf_upside_pct",
        "lynch_fair_value",
        "lynch_upside_pct",
        "valuation_triangulation",
        "valuation_upside_capped_pct",
        "shares_insiders_percent",
        "cyclical_peak_risk",
        "fcf_margin_pct",
        "current_ratio",
        "short_pct",
        "hedge_fund_buys",
        "portfolio_correlation",
    ],
    "Valuation": [
        "symbol",
        "description",
        "market_cap",
        "price",
        "pe_ratio",
        "pb_ratio",
        "ps_ratio",
        "peg_ratio",
        "ev_to_ebitda",
        "dcf_fair_value",
        "dcf_upside_pct",
        "lynch_fair_value",
        "lynch_upside_pct",
        "hedge_fund_buys",
    ],
    "Profitability": [
        "symbol",
        "description",
        "gross_margin_pct",
        "operating_margin_pct",
        "net_margin_pct",
        "roa_pct",
        "roe_pct",
        "roic_pct",
    ],
    "Growth": [
        "symbol",
        "description",
        "revenue_growth_5y_pct",
        "revenue_growth_3y_pct",
        "eps_growth_5y_pct",
        "eps_growth_3y_pct",
        "market_cap",
    ],
    "Financial Health": [
        "symbol",
        "description",
        "current_ratio",
        "debt_to_equity",
        "long_term_debt_to_equity",
        "fcf_margin_pct",
        "free_cash_flow_per_share",
    ],
    "Quality": [
        "symbol",
        "description",
        "market_cap",
        "price",
        "industry",
        "pe_ratio",
        "pt_upside_pct",
        "ev_to_ebitda",
        "short_pct",
        "rating",
        "dcf_fair_value",
        "dcf_upside_pct",
        "lynch_fair_value",
        "lynch_upside_pct",
        "valuation_triangulation",
        "valuation_upside_capped_pct",
        "shares_insiders_percent",
        "cyclical_peak_risk",
        "fcf_margin_pct",
        "current_ratio",
        "hedge_fund_buys",
    ],
    # The ratio duplicate stays in the schema and numeric filters, but never in
    # a display preset: 0.05 and 5.0 describe the same insider stake.
    "All Columns": [c for c in COLUMN_DISPLAY_NAMES if c != "shares_insiders_pct"],
}

# ── Numeric filter columns ──────────────────────────────────────────
NUMERIC_FILTER_COLUMNS: list[str] = [
    "market_cap",
    "pe_ratio",
    "pb_ratio",
    "ps_ratio",
    "peg_ratio",
    "ev_to_ebitda",
    "dividend_yield_pct",
    "gross_margin_pct",
    "operating_margin_pct",
    "net_margin_pct",
    "roa_pct",
    "roe_pct",
    "roic_pct",
    "current_ratio",
    "debt_to_equity",
    "fcf_margin_pct",
    "revenue_growth_5y_pct",
    "eps_growth_5y_pct",
    "beta",
    "price",
    "revenue_growth_3y_pct",
    "eps_growth_3y_pct",
    "free_cash_flow_per_share",
    "revenue_per_share",
    "book_value_per_share",
    "long_term_debt_to_equity",
    "asset_turnover",
    "eps_ttm",
    "net_income",
    "free_cash_flow",
    "fcf_growth_5y_pct",
    "net_income_growth_5y_pct",
    "return_cagr_5y_pct",
    "return_cagr_10y_pct",
    "return_cagr_15y_pct",
    "roa_5y_avg_pct",
    "roe_5y_avg_pct",
    "roic_5y_avg_pct",
    "shares_insiders_pct",
    "shares_insiders_percent",
    "cyclical_peak_risk",
    "valuation_upside_capped_pct",
    "short_pct",
    "pt_upside_pct",
    "dcf_fair_value",
    "dcf_upside_pct",
    "lynch_fair_value",
    "lynch_upside_pct",
    "hedge_fund_buys",
]

# ── Investment logic ─────────────────────────────────────────────────
# Industries where a low multiple on peak trailing earnings is a trap, not value.
CYCLICAL_INDUSTRIES: frozenset[str] = frozenset(
    {
        "Metals & Mining",
        "Gold",
        "Silver",
        "Agricultural Inputs",
        "Chemicals",
        "Semiconductors",
        "Semiconductor Equipment & Materials",
        "Engineering & Construction",
        "Oil & Gas E&P",
        "Oil & Gas Refining & Marketing",
        "Steel",
        "Building Products & Equipment",
    }
)

# ── Enum filter columns ─────────────────────────────────────────────
ENUM_FILTER_COLUMNS: list[str] = [
    "exchange",
    "type",
    "currency",
    "mic",
    "valuation_triangulation",
]
