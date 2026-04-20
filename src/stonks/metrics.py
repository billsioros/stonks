"""MetricsProvider — pulls fundamental data from Finnhub and normalizes it."""

from __future__ import annotations

import logging
import time
from typing import Any

import finnhub
import pandas as pd

from stonks.cache import LocalCache
from stonks.config import (
    FINNHUB_API_KEY,
    FINNHUB_RATE_LIMIT_CALLS,
    FINNHUB_RATE_LIMIT_WINDOW,
    METRICS_CACHE_TTL,
)

logger = logging.getLogger(__name__)

# Mapping from Finnhub metric keys → our column names
_METRIC_MAP: dict[str, str] = {
    "marketCapitalization": "market_cap",
    "peTTM": "pe_ratio",
    "pbQuarterly": "pb_ratio",
    "psTTM": "ps_ratio",
    "dividendYieldIndicatedAnnual": "dividend_yield_pct",
    "grossMarginTTM": "gross_margin_pct",
    "operatingMarginTTM": "operating_margin_pct",
    "netProfitMarginTTM": "net_margin_pct",
    "roaTTM": "roa_pct",
    "roeTTM": "roe_pct",
    "roicTTM": "roic_pct",
    "currentRatioQuarterly": "current_ratio",
    "totalDebt/totalEquityQuarterly": "debt_to_equity",
    "freeCashFlowTTM": "fcf_raw",
    "revenueTTM": "revenue_raw",
    "revenueGrowth5Y": "revenue_growth_5y_pct",
    "epsGrowth5Y": "eps_growth_5y_pct",
    "beta": "beta",
    "52WeekHigh": "week_52_high",
    "52WeekLow": "week_52_low",
    "10DayAverageTradingVolume": "avg_volume_10d",
    "pegRatio": "peg_ratio",
    "enterpriseValue": "enterprise_value",
    "enterpriseValue/ebitdaTTM": "ev_to_ebitda",
    "freeCashFlowPerShareTTM": "free_cash_flow_per_share",
    "revenuePerShareTTM": "revenue_per_share",
    "bookValuePerShareQuarterly": "book_value_per_share",
    "tangibleBookValuePerShareQuarterly": "tangible_book_value_per_share",
    "totalDebt/totalEquityQuarterly": "total_debt_to_total_equity",
    "longTermDebt/equityQuarterly": "long_term_debt_to_equity",
    "inventoryTurnoverTTM": "inventory_turnover",
    "receivablesTurnoverTTM": "receivables_turnover",
    "assetTurnoverTTM": "asset_turnover",
    "epsTTM": "eps_ttm",
    "epsGrowth3Y": "eps_growth_3y_pct",
    "revenueGrowth3Y": "revenue_growth_3y_pct",
}


class MetricsProvider:
    """Fetches and normalizes company fundamental metrics from Finnhub."""

    def __init__(
        self,
        api_key: str = FINNHUB_API_KEY,
        cache: LocalCache | None = None,
    ) -> None:
        self._client = finnhub.Client(api_key=api_key)
        self._cache = cache or LocalCache()
        self._call_times: list[float] = []

    def _rate_limit(self) -> None:
        """Simple sliding-window rate limiter."""
        now = time.time()
        self._call_times = [
            t for t in self._call_times
            if now - t < FINNHUB_RATE_LIMIT_WINDOW
        ]
        if len(self._call_times) >= FINNHUB_RATE_LIMIT_CALLS:
            sleep_for = FINNHUB_RATE_LIMIT_WINDOW - (now - self._call_times[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
        self._call_times.append(time.time())

    def fetch_metrics_raw(self, symbol: str) -> dict[str, Any]:
        """Fetch raw basic financials for a symbol (cached)."""
        cache_key = f"metrics_{symbol}"
        cached = self._cache.get(cache_key, ttl=METRICS_CACHE_TTL)
        if cached is not None:
            return cached

        self._rate_limit()
        try:
            data = self._client.company_basic_financials(symbol, "all")
            self._cache.set(cache_key, data)
            return data
        except Exception:
            logger.warning("Failed to fetch metrics for %s", symbol, exc_info=True)
            return {}

    def normalize_metrics(self, symbol: str, raw: dict[str, Any]) -> dict[str, Any]:
        """Extract and rename metrics into our standardized column names."""
        metrics: dict[str, Any] = raw.get("metric", {}) or {}
        row: dict[str, Any] = {"symbol": symbol}

        for finnhub_key, our_key in _METRIC_MAP.items():
            val = metrics.get(finnhub_key)
            if val is not None:
                row[our_key] = val

        # Compute FCF margin if both FCF and revenue are present
        fcf = row.get("fcf_raw")
        rev = row.get("revenue_raw")
        if fcf is not None and rev is not None and rev != 0:
            row["fcf_margin_pct"] = round((fcf / rev) * 100, 2)
        else:
            row["fcf_margin_pct"] = None

        # Price (use 52-week data as proxy if available)
        # Finnhub metric doesn't always have "price"; we'll get it from series or quote
        if "price" not in row:
            row["price"] = None

        return row

    def get_metrics_for_symbols(
        self,
        symbols: list[str],
        progress_callback: Any | None = None,
    ) -> pd.DataFrame:
        """Fetch and normalize metrics for a list of symbols.

        Args:
            symbols: List of ticker symbols.
            progress_callback: Optional callable(current, total) for progress tracking.

        Returns:
            DataFrame with one row per symbol.
        """
        rows: list[dict[str, Any]] = []
        total = len(symbols)

        for i, sym in enumerate(symbols):
            raw = self.fetch_metrics_raw(sym)
            if raw:
                row = self.normalize_metrics(sym, raw)
                rows.append(row)

            if progress_callback:
                progress_callback(i + 1, total)

        df = pd.DataFrame(rows)
        return df

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """Get a real-time quote for a symbol."""
        cache_key = f"quote_{symbol}"
        cached = self._cache.get(cache_key, ttl=300)  # 5 min TTL for quotes
        if cached is not None:
            return cached

        self._rate_limit()
        try:
            data = self._client.quote(symbol)
            self._cache.set(cache_key, data)
            return data
        except Exception:
            logger.warning("Failed to fetch quote for %s", symbol, exc_info=True)
            return {}
