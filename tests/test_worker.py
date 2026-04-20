"""Tests for the Background Worker module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from stonks.worker import sync_symbols_phase, job


@pytest.fixture
def mock_provider() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_store() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_cache() -> MagicMock:
    return MagicMock()


class TestWorker:
    def test_sync_symbols_phase_basic_success(
        self, mock_provider: MagicMock, mock_store: MagicMock, mock_cache: MagicMock
    ) -> None:
        symbols = ["AAPL"]
        mock_cache.get.return_value = None
        mock_provider.fetch_metrics_raw.return_value = {"metric": {"peTTM": 15}}

        fetched = sync_symbols_phase(
            symbols, mock_provider, mock_store, mock_cache, "basic"
        )

        assert fetched == 1
        mock_store.update_sync_status.assert_called_once_with(
            "AAPL", "basic", "success"
        )

    def test_sync_symbols_phase_basic_cached(
        self, mock_provider: MagicMock, mock_store: MagicMock, mock_cache: MagicMock
    ) -> None:
        symbols = ["AAPL"]
        mock_cache.get.return_value = {"metric": {"peTTM": 15}}

        fetched = sync_symbols_phase(
            symbols, mock_provider, mock_store, mock_cache, "basic"
        )

        assert fetched == 0
        mock_provider.fetch_metrics_raw.assert_not_called()
        mock_store.update_sync_status.assert_called_once_with(
            "AAPL", "basic", "success"
        )

    def test_sync_symbols_phase_candles_success(
        self, mock_provider: MagicMock, mock_store: MagicMock, mock_cache: MagicMock
    ) -> None:
        symbols = ["AAPL"]
        mock_cache.get.return_value = None
        mock_provider.fetch_candles_cached.return_value = {"s": "ok", "c": [100, 101]}

        fetched = sync_symbols_phase(
            symbols, mock_provider, mock_store, mock_cache, "candles"
        )

        assert fetched == 1
        mock_store.update_sync_status.assert_called_once_with(
            "AAPL", "candles", "success"
        )

    def test_sync_symbols_phase_failure(
        self, mock_provider: MagicMock, mock_store: MagicMock, mock_cache: MagicMock
    ) -> None:
        symbols = ["FAIL"]
        mock_cache.get.return_value = None
        mock_provider.fetch_metrics_raw.return_value = {}  # Empty response

        fetched = sync_symbols_phase(
            symbols, mock_provider, mock_store, mock_cache, "basic"
        )

        assert fetched == 0
        mock_store.update_sync_status.assert_called_once_with(
            "FAIL", "basic", "failed", "Empty response"
        )

    @patch("stonks.worker.LocalCache")
    @patch("stonks.worker.SQLiteStore")
    @patch("stonks.worker.UniverseLoader")
    @patch("stonks.worker.MetricsProvider")
    @patch("stonks.worker.sync_symbols_phase")
    @patch("stonks.worker.FINNHUB_API_KEY", "test_key")
    def test_job_flow(
        self,
        mock_sync_phase: MagicMock,
        mock_metrics_class: MagicMock,
        mock_universe_class: MagicMock,
        mock_store_class: MagicMock,
        mock_cache_class: MagicMock,
    ) -> None:
        # Instances
        mock_universe = mock_universe_class.return_value
        mock_store = mock_store_class.return_value

        # Setup mocks
        import pandas as pd

        mock_universe.get_common_stocks.return_value = pd.DataFrame(
            [{"symbol": "AAPL"}]
        )
        mock_store.get_failed_symbols.return_value = []
        mock_store.get_last_sync_info.return_value = {"total": 1}

        # Run job
        job()

        mock_universe.get_common_stocks.assert_called_once()
        mock_store.save_metadata.assert_called_with("universe_size", 1)
        assert mock_sync_phase.called
