"""Tests for the MetricsProvider module."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import pandas as pd

from stonks.metrics import MetricsProvider


@pytest.fixture
def mock_cache() -> MagicMock:
    return MagicMock()


@pytest.fixture
def provider(mock_cache: MagicMock) -> MetricsProvider:
    with patch("finnhub.Client") as mock_client_class:
        p = MetricsProvider(api_key="test_key", cache=mock_cache)
        # Store the mock client for easier access in tests
        p._mock_client = mock_client_class.return_value
        return p


class TestMetricsProvider:
    def test_rate_limit(self, provider: MetricsProvider) -> None:
        # Mock time.sleep to avoid waiting
        with patch("time.sleep") as mock_sleep:
            # Simulate 61 calls (limit is 60)
            for _ in range(61):
                provider._rate_limit()

            assert mock_sleep.called

    def test_fetch_metrics_raw_cached(
        self, provider: MetricsProvider, mock_cache: MagicMock
    ) -> None:
        mock_cache.get.return_value = {"metric": {"peTTM": 15}}

        result = provider.fetch_metrics_raw("AAPL")

        assert result == {"metric": {"peTTM": 15}}
        mock_cache.get.assert_called_once()
        provider._mock_client.company_basic_financials.assert_not_called()

    def test_fetch_metrics_raw_api(
        self, provider: MetricsProvider, mock_cache: MagicMock
    ) -> None:
        mock_cache.get.return_value = None
        provider._mock_client.company_basic_financials.return_value = {
            "metric": {"peTTM": 20}
        }

        result = provider.fetch_metrics_raw("AAPL")

        assert result == {"metric": {"peTTM": 20}}
        mock_cache.set.assert_called_once()
        provider._mock_client.company_basic_financials.assert_called_once_with(
            "AAPL", "all"
        )

    def test_fetch_metrics_raw_retry_on_429(
        self, provider: MetricsProvider, mock_cache: MagicMock
    ) -> None:
        mock_cache.get.return_value = None

        # Mock exception with status_code 429
        err = Exception("Rate limit")
        err.status_code = 429

        provider._mock_client.company_basic_financials.side_effect = [
            err,
            {"metric": {"peTTM": 25}},
        ]

        with patch("time.sleep"):
            result = provider.fetch_metrics_raw("AAPL")

        assert result == {"metric": {"peTTM": 25}}
        assert provider._mock_client.company_basic_financials.call_count == 2

    def test_normalize_metrics(self, provider: MetricsProvider) -> None:
        raw_data = {
            "symbol": "AAPL",
            "metric": {
                "marketCapitalization": 3000000,
                "peTTM": 30,
                "dividendYieldIndicatedAnnual": 0.5,
                "week_52_high": 200,
            },
            "series": {
                "annual": {
                    "roic": [{"v": 20}, {"v": 22}],
                    "freeCashFlow": [
                        {"v": 100},
                        {"v": 90},
                        {"v": 80},
                        {"v": 70},
                        {"v": 60},
                    ],
                }
            },
        }

        normalized = provider.normalize_metrics("AAPL", raw_data)

        assert normalized["symbol"] == "AAPL"
        assert normalized["market_cap"] == 3000000
        assert normalized["pe_ratio"] == 30
        assert normalized["dividend_yield_pct"] == 0.5
        assert normalized["roic_5y_avg_pct"] == 21.0
        assert "fcf_growth_5y_pct" in normalized

    def test_calculate_cagr(self, provider: MetricsProvider) -> None:
        # (121 / 100) ^ (1/2) - 1 = 1.1 - 1 = 0.1 (10%)
        assert provider._calculate_cagr(100, 121, 2) == 10.0
        assert provider._calculate_cagr(100, 0, 2) is None
        assert provider._calculate_cagr(100, 121, 0) is None

    def test_get_metrics_for_symbols_cache_only(
        self, provider: MetricsProvider, mock_cache: MagicMock
    ) -> None:
        mock_cache.get_many.return_value = {"metrics_AAPL": {"metric": {"peTTM": 30}}}

        df = provider.get_metrics_for_symbols(["AAPL", "MSFT"], cache_only=True)

        assert len(df) == 1
        assert df.iloc[0]["symbol"] == "AAPL"
        assert df.iloc[0]["pe_ratio"] == 30
