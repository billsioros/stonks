"""Tests for the Background Worker module."""

from unittest.mock import MagicMock, patch

import pandas as pd

from stonks.worker import job


class TestWorkerJob:
    @patch("stonks.worker.MetricsProvider")
    @patch("stonks.worker.SQLiteStore")
    @patch("stonks.worker.UniverseLoader")
    @patch("stonks.worker.FINNHUB_API_KEY", "test_key")
    def test_job_no_symbols(
        self,
        mock_universe_class: MagicMock,
        mock_store_class: MagicMock,
        mock_metrics_class: MagicMock,
    ) -> None:
        """Test job when no symbols are available."""
        mock_universe = mock_universe_class.return_value
        mock_universe.get_common_stocks.return_value = pd.DataFrame()

        job()

        mock_universe.get_common_stocks.assert_called_once()

    @patch("stonks.worker.MetricsProvider")
    @patch("stonks.worker.SQLiteStore")
    @patch("stonks.worker.UniverseLoader")
    @patch("stonks.worker.FINNHUB_API_KEY", "test_key")
    def test_job_all_symbols_synced_no_stale(
        self,
        mock_universe_class: MagicMock,
        mock_store_class: MagicMock,
        mock_metrics_class: MagicMock,
    ) -> None:
        """Test job skips all phases when data is synced and fresh."""
        mock_universe = mock_universe_class.return_value
        mock_store = mock_store_class.return_value
        mock_provider = mock_metrics_class.return_value

        symbols_df = pd.DataFrame([{"symbol": "AAPL"}, {"symbol": "GOOGL"}])
        mock_universe.get_common_stocks.return_value = symbols_df

        # All symbols synced for both basic and candles, none stale
        def mock_get_synced(data_type: str) -> list[str]:
            return ["AAPL", "GOOGL"]

        def mock_get_stale(data_type: str, stale_hours: int) -> list[str]:
            return []

        mock_store.get_synced_symbols.side_effect = mock_get_synced
        mock_store.get_stale_symbols.side_effect = mock_get_stale

        job()

        # Should not fetch anything
        mock_provider.fetch_metrics_raw.assert_not_called()
        mock_provider.fetch_candles_cached.assert_not_called()

    @patch("stonks.worker.MetricsProvider")
    @patch("stonks.worker.SQLiteStore")
    @patch("stonks.worker.UniverseLoader")
    @patch("stonks.worker.FINNHUB_API_KEY", "test_key")
    def test_phase1_missing_basic_fetches_both(
        self,
        mock_universe_class: MagicMock,
        mock_store_class: MagicMock,
        mock_metrics_class: MagicMock,
    ) -> None:
        """Test Phase1: missing basic fetches basic + candles for each symbol."""
        mock_universe = mock_universe_class.return_value
        mock_store = mock_store_class.return_value
        mock_provider = mock_metrics_class.return_value

        symbols_df = pd.DataFrame([{"symbol": "AAPL"}, {"symbol": "GOOGL"}])
        mock_universe.get_common_stocks.return_value = symbols_df

        # No symbols synced for basic or candles
        def mock_get_synced(data_type: str) -> list[str]:
            return []

        def mock_get_stale(data_type: str, stale_hours: int) -> list[str]:
            return []

        mock_store.get_synced_symbols.side_effect = mock_get_synced
        mock_store.get_stale_symbols.side_effect = mock_get_stale

        mock_provider.fetch_metrics_raw.return_value = {"metric": {"peTTM": 15}}
        mock_provider.normalize_metrics.return_value = {"pe_ratio": 15}
        mock_provider.fetch_candles_cached.return_value = {
            "s": "ok",
            "c": [100, 110, 120],
        }

        job()

        # Phase1: Should fetch basic for both symbols
        assert mock_provider.fetch_metrics_raw.call_count == 2
        # Phase1: Should also fetch candles for both symbols (immediately after basic)
        assert mock_provider.fetch_candles_cached.call_count == 2
        # Phase2, 3, 4 should not run (no missing/stale data)
        assert mock_store.save_stock.call_count == 4  # 2 basic + 2 candles

    @patch("stonks.worker.MetricsProvider")
    @patch("stonks.worker.SQLiteStore")
    @patch("stonks.worker.UniverseLoader")
    @patch("stonks.worker.FINNHUB_API_KEY", "test_key")
    def test_phase2_missing_candles_fetches_only_candles(
        self,
        mock_universe_class: MagicMock,
        mock_store_class: MagicMock,
        mock_metrics_class: MagicMock,
    ) -> None:
        """Test Phase2: missing candles fetches only candles (basic exists)."""
        mock_universe = mock_universe_class.return_value
        mock_store = mock_store_class.return_value
        mock_provider = mock_metrics_class.return_value

        symbols_df = pd.DataFrame([{"symbol": "AAPL"}])
        mock_universe.get_common_stocks.return_value = symbols_df

        # Basic synced, candles not synced
        def mock_get_synced(data_type: str) -> list[str]:
            if data_type == "basic":
                return ["AAPL"]
            return []  # candles not synced

        def mock_get_stale(data_type: str, stale_hours: int) -> list[str]:
            return []  # No stale data

        mock_store.get_synced_symbols.side_effect = mock_get_synced
        mock_store.get_stale_symbols.side_effect = mock_get_stale

        mock_provider.fetch_candles_cached.return_value = {
            "s": "ok",
            "c": [100, 110, 120],
        }

        job()

        # Should not fetch basic (already synced)
        mock_provider.fetch_metrics_raw.assert_not_called()
        # Should fetch candles
        mock_provider.fetch_candles_cached.assert_called_once_with("AAPL", years=15)

    @patch("stonks.worker.MetricsProvider")
    @patch("stonks.worker.SQLiteStore")
    @patch("stonks.worker.UniverseLoader")
    @patch("stonks.worker.FINNHUB_API_KEY", "test_key")
    def test_phase3_stale_basic_fetches_both(
        self,
        mock_universe_class: MagicMock,
        mock_store_class: MagicMock,
        mock_metrics_class: MagicMock,
    ) -> None:
        """Test Phase3: stale basic refetches basic + candles."""
        mock_universe = mock_universe_class.return_value
        mock_store = mock_store_class.return_value
        mock_provider = mock_metrics_class.return_value

        symbols_df = pd.DataFrame([{"symbol": "AAPL"}])
        mock_universe.get_common_stocks.return_value = symbols_df

        # Basic and candles synced, but basic is stale
        def mock_get_synced(data_type: str) -> list[str]:
            return ["AAPL"]

        def mock_get_stale(data_type: str, stale_hours: int) -> list[str]:
            if data_type == "basic":
                return ["AAPL"]  # Stale basic
            return []  # Candles not stale

        mock_store.get_synced_symbols.side_effect = mock_get_synced
        mock_store.get_stale_symbols.side_effect = mock_get_stale

        mock_provider.fetch_metrics_raw.return_value = {"metric": {"peTTM": 15}}
        mock_provider.normalize_metrics.return_value = {"pe_ratio": 15}
        mock_provider.fetch_candles_cached.return_value = {
            "s": "ok",
            "c": [100, 110, 120],
        }

        job()

        # Should refetch basic
        mock_provider.fetch_metrics_raw.assert_called_once_with("AAPL")
        # Should also fetch candles (might be stale too)
        mock_provider.fetch_candles_cached.assert_called_once_with("AAPL", years=15)

    @patch("stonks.worker.MetricsProvider")
    @patch("stonks.worker.SQLiteStore")
    @patch("stonks.worker.UniverseLoader")
    @patch("stonks.worker.FINNHUB_API_KEY", "test_key")
    def test_phase4_stale_candles_only(
        self,
        mock_universe_class: MagicMock,
        mock_store_class: MagicMock,
        mock_metrics_class: MagicMock,
    ) -> None:
        """Test Phase4: stale candles refetches only candles."""
        mock_universe = mock_universe_class.return_value
        mock_store = mock_store_class.return_value
        mock_provider = mock_metrics_class.return_value

        symbols_df = pd.DataFrame([{"symbol": "AAPL"}])
        mock_universe.get_common_stocks.return_value = symbols_df

        # Both synced, only candles stale
        def mock_get_synced(data_type: str) -> list[str]:
            return ["AAPL"]

        def mock_get_stale(data_type: str, stale_hours: int) -> list[str]:
            if data_type == "candles":
                return ["AAPL"]  # Stale candles
            return []  # Basic not stale

        mock_store.get_synced_symbols.side_effect = mock_get_synced
        mock_store.get_stale_symbols.side_effect = mock_get_stale

        mock_provider.fetch_candles_cached.return_value = {
            "s": "ok",
            "c": [100, 110, 120],
        }

        job()

        # Should not refetch basic
        mock_provider.fetch_metrics_raw.assert_not_called()
        # Should refetch candles
        mock_provider.fetch_candles_cached.assert_called_once_with("AAPL", years=15)

    @patch("stonks.worker.MetricsProvider")
    @patch("stonks.worker.SQLiteStore")
    @patch("stonks.worker.UniverseLoader")
    @patch("stonks.worker.FINNHUB_API_KEY", "test_key")
    def test_job_handles_failed_sync(
        self,
        mock_universe_class: MagicMock,
        mock_store_class: MagicMock,
        mock_metrics_class: MagicMock,
    ) -> None:
        """Test job handles failed syncs properly."""
        mock_universe = mock_universe_class.return_value
        mock_store = mock_store_class.return_value
        mock_provider = mock_metrics_class.return_value

        symbols_df = pd.DataFrame([{"symbol": "FAIL"}])
        mock_universe.get_common_stocks.return_value = symbols_df

        # No symbols synced
        def mock_get_synced(data_type: str) -> list[str]:
            return []

        def mock_get_stale(data_type: str, stale_hours: int) -> list[str]:
            return []

        mock_store.get_synced_symbols.side_effect = mock_get_synced
        mock_store.get_stale_symbols.side_effect = mock_get_stale

        # Return empty response for metrics (simulating failure)
        mock_provider.fetch_metrics_raw.return_value = {}

        job()

        # Should update status to failed for basic
        mock_store.update_sync_status.assert_any_call(
            "FAIL", "basic", "failed", "No data"
        )
        # Should not save stock data
        mock_store.save_stock.assert_not_called()

    @patch("stonks.worker.MetricsProvider")
    @patch("stonks.worker.SQLiteStore")
    @patch("stonks.worker.UniverseLoader")
    @patch("stonks.worker.FINNHUB_API_KEY", "test_key")
    def test_job_no_api_key(
        self,
        mock_universe_class: MagicMock,
        mock_store_class: MagicMock,
        mock_metrics_class: MagicMock,
    ) -> None:
        """Test job exits early when no API key."""
        with patch("stonks.worker.FINNHUB_API_KEY", ""):
            job()

            # Should not try to load symbols
            mock_universe_class.return_value.get_common_stocks.assert_not_called()

    @patch("stonks.worker.MetricsProvider")
    @patch("stonks.worker.SQLiteStore")
    @patch("stonks.worker.UniverseLoader")
    @patch("stonks.worker.FINNHUB_API_KEY", "test_key")
    def test_symbol_not_processed_in_multiple_phases(
        self,
        mock_universe_class: MagicMock,
        mock_store_class: MagicMock,
        mock_metrics_class: MagicMock,
    ) -> None:
        """Test that a symbol is only processed once across all phases."""
        mock_universe = mock_universe_class.return_value
        mock_store = mock_store_class.return_value
        mock_provider = mock_metrics_class.return_value

        symbols_df = pd.DataFrame([{"symbol": "AAPL"}])
        mock_universe.get_common_stocks.return_value = symbols_df

        # AAPL has no basic data (Phase1) but also has stale candles (would be Phase4)
        def mock_get_synced(data_type: str) -> list[str]:
            if data_type == "basic":
                return []  # No basic synced
            return []  # No candles synced either

        def mock_get_stale(data_type: str, stale_hours: int) -> list[str]:
            if data_type == "candles":
                return ["AAPL"]  # Stale candles
            return []

        mock_store.get_synced_symbols.side_effect = mock_get_synced
        mock_store.get_stale_symbols.side_effect = mock_get_stale

        mock_provider.fetch_metrics_raw.return_value = {"metric": {"peTTM": 15}}
        mock_provider.normalize_metrics.return_value = {"pe_ratio": 15}
        mock_provider.fetch_candles_cached.return_value = {
            "s": "ok",
            "c": [100, 110, 120],
        }

        job()

        # AAPL should only be processed in Phase1 (highest priority)
        # Should NOT also be processed in Phase4
        assert mock_provider.fetch_metrics_raw.call_count == 1
        assert mock_provider.fetch_candles_cached.call_count == 1
