"""Tests for the MetricsProvider module."""

from unittest.mock import patch

import pytest

from stonks.metrics import MetricsProvider


@pytest.fixture
def provider() -> MetricsProvider:
    with patch("finnhub.Client") as mock_client_class:
        p = MetricsProvider(api_key="test_key")
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

    def test_fetch_metrics_raw_retry_on_429(self, provider: MetricsProvider) -> None:
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
