"""Tests for the UniverseLoader module."""

from unittest.mock import patch

import pytest

from stonks.universe import UniverseLoader, _symbols_cache


@pytest.fixture
def loader() -> UniverseLoader:
    """Create a loader with cleared cache."""
    # Clear the module-level cache before each test
    _symbols_cache.clear()
    with patch("finnhub.Client") as mock_client_class:
        l = UniverseLoader(api_key="test_key")
        l._mock_client = mock_client_class.return_value
        return l


class TestUniverseLoader:
    def test_load_symbols_api(self, loader: UniverseLoader) -> None:
        """Test loading symbols from API."""
        loader._mock_client.stock_symbols.return_value = [
            {"symbol": "TSLA", "type": "Common Stock"},
        ]

        df = loader.load_symbols("US")

        assert len(df) == 1
        assert df.iloc[0]["symbol"] == "TSLA"
        loader._mock_client.stock_symbols.assert_called_once_with("US")

    def test_load_symbols_handles_exception(self, loader: UniverseLoader) -> None:
        """Test that exceptions are handled gracefully."""
        loader._mock_client.stock_symbols.side_effect = Exception("API Error")

        df = loader.load_symbols("US")

        assert df.empty

    def test_get_common_stocks(self, loader: UniverseLoader) -> None:
        """Test filtering for common stocks only."""
        loader._mock_client.stock_symbols.return_value = [
            {"symbol": "AAPL", "type": "Common Stock"},
            {"symbol": "ETF1", "type": "ETF"},
        ]

        df = loader.get_common_stocks("US")

        assert len(df) == 1
        assert df.iloc[0]["symbol"] == "AAPL"
        assert df.iloc[0]["type"] == "Common Stock"

    def test_load_symbols_empty_response(self, loader: UniverseLoader) -> None:
        """Test handling of empty API response."""
        loader._mock_client.stock_symbols.return_value = []

        df = loader.load_symbols("US")

        assert df.empty

    def test_load_symbols_caches_result(self, loader: UniverseLoader) -> None:
        """Test that symbols are cached."""
        loader._mock_client.stock_symbols.return_value = [
            {"symbol": "AAPL", "type": "Common Stock"},
        ]

        # First call
        df1 = loader.load_symbols("US")
        # Second call should use cache
        df2 = loader.load_symbols("US")

        assert len(df1) == 1
        assert loader._mock_client.stock_symbols.call_count == 1  # Only called once
