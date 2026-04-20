"""Tests for the ScreenerEngine module."""

from __future__ import annotations

import pandas as pd
import pytest

from stonks.engine import ScreenerEngine


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN"],
            "description": [
                "Apple Inc",
                "Alphabet Inc",
                "Microsoft Corp",
                "Tesla Inc",
                "Amazon.com",
            ],
            "exchange": ["NASDAQ", "NASDAQ", "NASDAQ", "NASDAQ", "NASDAQ"],
            "type": ["Common Stock"] * 5,
            "market_cap": [3000000, 2000000, 2500000, 800000, 1700000],
            "pe_ratio": [28.5, 25.3, 32.1, 65.2, 55.0],
            "roe_pct": [145.0, 28.5, 38.2, 22.3, 18.5],
            "dividend_yield_pct": [0.55, None, 0.75, 0.0, 0.0],
            "gross_margin_pct": [45.3, 56.2, 69.1, 18.2, 47.6],
        }
    )


@pytest.fixture
def engine(sample_df: pd.DataFrame) -> ScreenerEngine:
    return ScreenerEngine(sample_df)


class TestScreenerEngine:
    def test_apply_filters_min(self, engine: ScreenerEngine) -> None:
        result = engine.apply_filters({"pe_ratio": {"min": 30}})
        assert len(result) == 3  # MSFT, TSLA, AMZN
        assert set(result["symbol"].tolist()) == {"MSFT", "TSLA", "AMZN"}

    def test_apply_filters_max(self, engine: ScreenerEngine) -> None:
        result = engine.apply_filters({"pe_ratio": {"max": 30}})
        assert len(result) == 2  # AAPL, GOOGL

    def test_apply_filters_range(self, engine: ScreenerEngine) -> None:
        result = engine.apply_filters({"pe_ratio": {"min": 25, "max": 35}})
        assert len(result) == 3  # AAPL, GOOGL, MSFT

    def test_apply_filters_enum(self, engine: ScreenerEngine) -> None:
        result = engine.apply_filters({"symbol": {"values": ["AAPL", "MSFT"]}})
        assert len(result) == 2

    def test_apply_filters_missing_column(self, engine: ScreenerEngine) -> None:
        result = engine.apply_filters({"nonexistent": {"min": 10}})
        assert len(result) == 5  # no filter applied

    def test_search_by_symbol(
        self, engine: ScreenerEngine, sample_df: pd.DataFrame
    ) -> None:
        result = engine.search(sample_df, "AAPL")
        assert len(result) == 1
        assert result.iloc[0]["symbol"] == "AAPL"

    def test_search_by_name(
        self, engine: ScreenerEngine, sample_df: pd.DataFrame
    ) -> None:
        result = engine.search(sample_df, "microsoft")
        assert len(result) == 1
        assert result.iloc[0]["symbol"] == "MSFT"

    def test_search_partial(
        self, engine: ScreenerEngine, sample_df: pd.DataFrame
    ) -> None:
        result = engine.search(sample_df, "inc")
        assert len(result) == 3  # Apple Inc, Alphabet Inc, Tesla Inc

    def test_search_empty(
        self, engine: ScreenerEngine, sample_df: pd.DataFrame
    ) -> None:
        result = engine.search(sample_df, "")
        assert len(result) == 5

    def test_sort_ascending(
        self, engine: ScreenerEngine, sample_df: pd.DataFrame
    ) -> None:
        result = engine.sort(sample_df, "pe_ratio", ascending=True)
        assert result.iloc[0]["symbol"] == "GOOGL"

    def test_sort_descending(
        self, engine: ScreenerEngine, sample_df: pd.DataFrame
    ) -> None:
        result = engine.sort(sample_df, "pe_ratio", ascending=False)
        assert result.iloc[0]["symbol"] == "TSLA"

    def test_paginate(self, engine: ScreenerEngine, sample_df: pd.DataFrame) -> None:
        page_df, total_pages = engine.paginate(sample_df, page=1, page_size=2)
        assert len(page_df) == 2
        assert total_pages == 3

    def test_paginate_last_page(
        self, engine: ScreenerEngine, sample_df: pd.DataFrame
    ) -> None:
        page_df, total_pages = engine.paginate(sample_df, page=3, page_size=2)
        assert len(page_df) == 1
        assert total_pages == 3

    def test_run_screen_full(self, engine: ScreenerEngine) -> None:
        page_df, total_pages, total_matching = engine.run_screen(
            filters={"pe_ratio": {"min": 30}},
            search_query="",
            sort_column="pe_ratio",
            sort_ascending=True,
            page=1,
            page_size=10,
        )
        assert total_matching == 3
        assert total_pages == 1
        assert len(page_df) == 3
        assert page_df.iloc[0]["symbol"] == "MSFT"  # lowest PE among filtered

    def test_run_screen_with_search(self, engine: ScreenerEngine) -> None:
        page_df, total_pages, total_matching = engine.run_screen(
            search_query="tesla",
            page=1,
            page_size=10,
        )
        assert total_matching == 1
        assert page_df.iloc[0]["symbol"] == "TSLA"

    def test_apply_filters_empty(self, engine: ScreenerEngine) -> None:
        result = engine.apply_filters({})
        assert len(result) == 5

    def test_sort_nonexistent_column(
        self, engine: ScreenerEngine, sample_df: pd.DataFrame
    ) -> None:
        result = engine.sort(sample_df, "mystery_column")
        pd.testing.assert_frame_equal(result, sample_df)

    def test_paginate_empty_df(self, engine: ScreenerEngine) -> None:
        empty_df = pd.DataFrame(columns=["symbol"])
        page_df, total_pages = engine.paginate(empty_df, page=1, page_size=10)
        assert page_df.empty
        assert total_pages == 1
