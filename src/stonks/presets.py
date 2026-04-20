"""Predefined popular screener presets."""

from __future__ import annotations

from typing import Any

# Each preset is a dict with:
#   name: display name
#   description: one-line description
#   filters: dict of column → {min, max} or {values: [...]}
#   view_preset: which view preset to use
#   sort_column: default sort column
#   sort_ascending: default sort direction

POPULAR_SCREENS: list[dict[str, Any]] = [
    {
        "name": "💎 The Quality Screen",
        "description": "Premium stocks with high ROIC, high margins, and strong FCF growth",
        "filters": {
            "roic_5y_avg_pct": {"min": 10},
            "gross_margin_pct": {"min": 10},
            "free_cash_flow": {"min": 1},
            "return_cagr_5y_pct": {"min": 10},
            "operating_margin_pct": {"min": 10},
            "net_income": {"min": 1},
            "fcf_growth_5y_pct": {"min": 10},
            "debt_to_equity": {"max": 1.0},
            "return_cagr_15y_pct": {"min": 10},
            "return_cagr_10y_pct": {"min": 10},
            "roa_5y_avg_pct": {"min": 10},
            "roe_5y_avg_pct": {"min": 10},
            "net_income_growth_5y_pct": {"min": 10},
            "shares_insiders_pct": {"min": 0.01},
        },
        "view_preset": "Quality",
        "sort_column": "roic_5y_avg_pct",
        "sort_ascending": False,
    },
    {
        "name": "🏆 Quality Compounders",
        "description": "High ROE, high margins, low debt — the Buffett picks",
        "filters": {
            "roe_pct": {"min": 15},
            "gross_margin_pct": {"min": 40},
            "debt_to_equity": {"max": 1.0},
            "market_cap": {"min": 1000},
        },
        "view_preset": "Profitability",
        "sort_column": "roe_pct",
        "sort_ascending": False,
    },
    {
        "name": "💰 Dividend Champions",
        "description": "Solid dividend yield with sustainable payout",
        "filters": {
            "dividend_yield_pct": {"min": 2.5},
            "pe_ratio": {"min": 5, "max": 25},
            "market_cap": {"min": 2000},
        },
        "view_preset": "Overview",
        "sort_column": "dividend_yield_pct",
        "sort_ascending": False,
    },
    {
        "name": "📈 Growth Machines",
        "description": "High revenue and EPS growth over the past 5 years",
        "filters": {
            "revenue_growth_5y_pct": {"min": 15},
            "eps_growth_5y_pct": {"min": 15},
            "market_cap": {"min": 500},
        },
        "view_preset": "Growth",
        "sort_column": "revenue_growth_5y_pct",
        "sort_ascending": False,
    },
    {
        "name": "🏷️ Deep Value",
        "description": "Low P/E, low P/B, potentially undervalued",
        "filters": {
            "pe_ratio": {"min": 1, "max": 12},
            "pb_ratio": {"max": 1.5},
            "market_cap": {"min": 500},
        },
        "view_preset": "Valuation",
        "sort_column": "pe_ratio",
        "sort_ascending": True,
    },
    {
        "name": "🏦 Large Cap Blue Chips",
        "description": "Mega-cap stocks with strong fundamentals",
        "filters": {
            "market_cap": {"min": 50000},
            "roe_pct": {"min": 10},
        },
        "view_preset": "Overview",
        "sort_column": "market_cap",
        "sort_ascending": False,
    },
    {
        "name": "🔬 Small Cap Gems",
        "description": "Small caps with strong growth and profitability",
        "filters": {
            "market_cap": {"min": 300, "max": 2000},
            "revenue_growth_5y_pct": {"min": 10},
            "roe_pct": {"min": 10},
        },
        "view_preset": "Growth",
        "sort_column": "revenue_growth_5y_pct",
        "sort_ascending": False,
    },
    {
        "name": "💪 Strong Balance Sheet",
        "description": "Low debt, high current ratio, strong FCF",
        "filters": {
            "debt_to_equity": {"max": 0.5},
            "current_ratio": {"min": 2.0},
            "market_cap": {"min": 1000},
        },
        "view_preset": "Financial Health",
        "sort_column": "current_ratio",
        "sort_ascending": False,
    },
    {
        "name": "⚡ Momentum Leaders",
        "description": "Strong recent growth with high ROIC",
        "filters": {
            "roic_pct": {"min": 15},
            "revenue_growth_3y_pct": {"min": 10},
            "market_cap": {"min": 1000},
        },
        "view_preset": "Profitability",
        "sort_column": "roic_pct",
        "sort_ascending": False,
    },
]
