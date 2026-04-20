"""Tests for the UniverseLoader module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import pandas as pd

from stonks.universe import UniverseLoader


@pytest.fixture
def mock_cache() -> MagicMock:
    return MagicMock()


@pytest.fixture
def loader(mock_cache: MagicMock) -> UniverseLoader:
    with patch("finnhub.Client") as mock_client_class:
        l = UniverseLoader(api_key="test_key", cache=mock_cache)
        l._mock_client = mock_client_class.return_value
        return l


class TestUniverseLoader:
    def test_load_symbols_cached(
        self, loader: UniverseLoader, mock_cache: MagicMock
    ) -> None:
        mock_cache.get.return_value = [
            {"symbol": "AAPL", "type": "Common Stock"},
            {"symbol": "GOOGL", "type": "Common Stock"},
        ]

        df = loader.load_symbols("US")

        assert len(df) == 2
        assert df.iloc[0]["symbol"] == "AAPL"
        mock_cache.get.assert_called_once()
        loader._mock_client.stock_symbols.assert_not_called()

    def test_load_symbols_api(
        self, loader: UniverseLoader, mock_cache: MagicMock
    ) -> None:
        mock_cache.get.return_value = None
        loader._mock_client.stock_symbols.return_value = [
            {"symbol": "TSLA", "type": "Common Stock"},
        ]

        df = loader.load_symbols("US")

        assert len(df) == 1
        assert df.iloc[0]["symbol"] == "TSLA"
        mock_cache.set.assert_called_once()
        loader._mock_client.stock_symbols.assert_called_once_with("US")

    def test_load_symbols_retry_on_429(
        self, loader: UniverseLoader, mock_cache: MagicMock
    ) -> None:
        mock_cache.get.return_value = None

        err = Exception("Rate limit")
        err.status_code = 429

        loader._mock_client.stock_symbols.side_effect = [err, [{"symbol": "MSFT"}]]

        with patch("time.sleep"):
            df = loader.load_symbols("US")

        assert len(df) == 1
        assert df.iloc[0]["symbol"] == "MSFT"
        assert loader._mock_client.stock_symbols.call_count == 2

    def test_get_common_stocks(
        self, loader: UniverseLoader, mock_cache: MagicMock
    ) -> None:
        mock_cache.get.return_value = [
            {"symbol": "AAPL", "type": "Common Stock"},
            {"symbol": "ETF1", "type": "ETF"},
        ]

        df = loader.get_common_stocks("US")

        assert len(df) == 1
        assert df.iloc[0]["symbol"] == "AAPL"
        assert df.iloc[0]["type"] == "Common Stock"

    def test_load_symbols_empty_response(
        self, loader: UniverseLoader, mock_cache: MagicMock
    ) -> None:
        mock_cache.get.return_value = None
        loader._mock_client.stock_symbols.return_value = []

        df = loader.load_symbols("US")

        assert df.empty
