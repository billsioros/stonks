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
    "freeCashFlowTTM": "free_cash_flow",
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
    "longTermDebt/equityQuarterly": "long_term_debt_to_equity",
    "inventoryTurnoverTTM": "inventory_turnover",
    "receivablesTurnoverTTM": "receivables_turnover",
    "assetTurnoverTTM": "asset_turnover",
    "epsTTM": "eps_ttm",
    "epsGrowth3Y": "eps_growth_3y_pct",
    "revenueGrowth3Y": "revenue_growth_3y_pct",
    "netIncomeEmployeeTTM": "net_income",
    "sharesInsiders": "shares_insiders_pct",
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
            t for t in self._call_times if now - t < FINNHUB_RATE_LIMIT_WINDOW
        ]
        if len(self._call_times) >= FINNHUB_RATE_LIMIT_CALLS:
            sleep_for = FINNHUB_RATE_LIMIT_WINDOW - (now - self._call_times[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
        self._call_times.append(time.time())

    def fetch_metrics_raw(
        self, symbol: str, retries: int = 3, backoff: float = 1.0
    ) -> dict[str, Any]:
        """Fetch raw basic financials for a symbol (cached) with backoff for 429s."""
        cache_key = f"metrics_{symbol}"
        cached = self._cache.get(cache_key, ttl=METRICS_CACHE_TTL)
        if cached is not None:
            return cached

        for attempt in range(retries):
            self._rate_limit()
            try:
                data = self._client.company_basic_financials(symbol, "all")
                self._cache.set(cache_key, data)
                return data
            except Exception as e:
                # Handle 429 Rate Limit
                if hasattr(e, "status_code") and e.status_code == 429:
                    wait = backoff * (2**attempt)
                    logger.warning(
                        "Rate limit (429) hit for %s. Retrying in %.1fs (Attempt %d/%d)",
                        symbol,
                        wait,
                        attempt + 1,
                        retries,
                    )
                    time.sleep(wait)
                    continue

                # Generic log and fail
                logger.warning("Failed to fetch metrics for %s: %s", symbol, e)
                return {}

        logger.error(
            "Exhausted retries for %s after %d attempts due to rate limits.",
            symbol,
            retries,
        )
        return {}

    def fetch_candles_cached(self, symbol: str, years: int = 15) -> dict[str, Any]:
        """Fetch historical candles with local caching."""
        cache_key = f"candles_{symbol}_{years}y"
        cached = self._cache.get(cache_key, ttl=86400 * 7)  # 1 week TTL
        if cached is not None:
            return cached

        to_ts = int(time.time())
        from_ts = to_ts - (years * 365 * 24 * 3600)

        self._rate_limit()
        try:
            data = self._client.stock_candles(symbol, "D", from_ts, to_ts)
            if data and data.get("s") == "ok":
                self._cache.set(cache_key, data)
                return data
        except Exception:
            logger.warning("Failed to fetch candles for %s", symbol)

        return {}

    def _calculate_cagr(
        self, start_price: float, end_price: float, years: float
    ) -> float | None:
        """Calculate Compound Annual Growth Rate."""
        if start_price <= 0 or end_price <= 0 or years <= 0:
            return None
        try:
            return round(((end_price / start_price) ** (1 / years) - 1) * 100, 2)
        except Exception:
            return None

    def normalize_metrics(self, symbol: str, raw: dict[str, Any]) -> dict[str, Any]:
        """Extract and rename basic financials (no heavy candles)."""
        metrics: dict[str, Any] = raw.get("metric", {}) or {}
        series: dict[str, Any] = raw.get("series", {}) or {}
        row: dict[str, Any] = {"symbol": symbol}

        for finnhub_key, our_key in _METRIC_MAP.items():
            val = metrics.get(finnhub_key)
            if val is not None:
                row[our_key] = val

        # ── 5Y Averages from Series ──────────────────────────────────
        annual = series.get("annual", {})
        for metric_name, row_name in [
            ("roic", "roic_5y_avg_pct"),
            ("roe", "roe_5y_avg_pct"),
            ("roa", "roa_5y_avg_pct"),
        ]:
            vals = annual.get(metric_name, [])
            if vals:
                # Average up to last 5 years
                period_vals = [v.get("v") for v in vals[:5] if v.get("v") is not None]
                if period_vals:
                    row[row_name] = round(sum(period_vals) / len(period_vals), 2)

        # Growth metrics from series if not in metrics
        if "fcf_growth_5y_pct" not in row:
            fcf_vals = annual.get("freeCashFlow", [])
            if len(fcf_vals) >= 5:
                v_recent = fcf_vals[0].get("v")
                v_old = fcf_vals[4].get("v")
                if v_recent and v_old and v_old > 0:
                    row["fcf_growth_5y_pct"] = self._calculate_cagr(v_old, v_recent, 5)

        if "net_income_growth_5y_pct" not in row:
            ni_vals = annual.get("netIncome", [])
            if len(ni_vals) >= 5:
                v_recent = ni_vals[0].get("v")
                v_old = ni_vals[4].get("v")
                if v_recent and v_old and v_old > 0:
                    row["net_income_growth_5y_pct"] = self._calculate_cagr(
                        v_old, v_recent, 5
                    )

        # ── Derived ──────────────────────────────────────────────────
        # Compute FCF margin
        fcf = row.get("free_cash_flow")
        rev = row.get("revenue_raw")
        if fcf is not None and rev is not None and rev != 0:
            row["fcf_margin_pct"] = round((fcf / rev) * 100, 2)

        # Fallback price from basic metrics (52w high as proxy)
        row["price"] = row.get("week_52_high")

        return row

    def enrich_with_candles(
        self, df: pd.DataFrame, years: int = 15, progress_callback: Any | None = None
    ) -> pd.DataFrame:
        """Fetch candles for each ticker in the DF and add CAGR columns."""
        if df.empty:
            return df

        symbols = df["symbol"].tolist()
        total = len(symbols)

        cagr_rows: list[dict[str, Any]] = []
        for i, sym in enumerate(symbols):
            candles = self.fetch_candles_cached(sym, years)
            ext: dict[str, Any] = {"symbol": sym}

            if candles and candles.get("s") == "ok":
                c = candles.get("c", [])
                if c:
                    current_price = c[-1]
                    ext["price"] = current_price
                    for yrs in [5, 10, 15]:
                        idx = -(yrs * 252)
                        if abs(idx) < len(c):
                            ext[f"return_cagr_{yrs}y_pct"] = self._calculate_cagr(
                                c[idx], current_price, yrs
                            )

            cagr_rows.append(ext)
            if progress_callback:
                progress_callback(i + 1, total)

        cagr_df = pd.DataFrame(cagr_rows)
        # Combine with original DF, prioritizing the new price and CAGR data
        for col in cagr_df.columns:
            if col == "symbol":
                continue
            df[col] = cagr_df.set_index("symbol")[col].reindex(df["symbol"]).values

        return df

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
