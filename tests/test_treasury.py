"""Tests for the ten-year Treasury yield source behind the DCF discount rate."""

import json

from stonks import treasury

SAMPLE_CSV = """observation_date,DGS10
2026-11-13,5.15
2026-11-16,5.12
2026-11-17,.
2026-11-18,5.07
"""

SAMPLE_YAHOO = json.dumps(
    {
        "chart": {
            "result": [
                {
                    "indicators": {
                        "quote": [{"close": [5.01, 4.98, None, 4.946]}],
                    }
                }
            ]
        }
    }
)


class TestParseYahooYield:
    def test_returns_newest_non_null_close(self) -> None:
        assert treasury.parse_yahoo_yield(SAMPLE_YAHOO) == 4.946

    def test_unusable_payloads_yield_none(self) -> None:
        assert treasury.parse_yahoo_yield("not json") is None
        assert treasury.parse_yahoo_yield(json.dumps({"chart": {"result": []}})) is None
        assert (
            treasury.parse_yahoo_yield(json.dumps({"chart": {"result": None}})) is None
        )

    def test_all_null_closes_yield_none(self) -> None:
        payload = json.dumps(
            {"chart": {"result": [{"indicators": {"quote": [{"close": [None]}]}}]}}
        )

        assert treasury.parse_yahoo_yield(payload) is None


class TestParseFredYield:
    def test_returns_latest_populated_value(self) -> None:
        assert treasury.parse_fred_yield(SAMPLE_CSV) == 5.07

    def test_holiday_gaps_are_skipped(self) -> None:
        payload = "observation_date,DGS10\n2026-11-17,.\n2026-11-16,5.12\n"

        assert treasury.parse_fred_yield(payload) == 5.12

    def test_header_only_yields_none(self) -> None:
        assert treasury.parse_fred_yield("observation_date,DGS10\n") is None

    def test_garbage_yields_none(self) -> None:
        assert treasury.parse_fred_yield("") is None
        assert treasury.parse_fred_yield("<html>blocked</html>") is None


class TestFetchTreasuryYield:
    def test_primary_source_wins(self) -> None:
        urls = []

        def fake_fetch(url: str) -> str:
            urls.append(url)
            return SAMPLE_YAHOO

        assert treasury.fetch_treasury_yield_pct(fake_fetch) == 4.946
        assert urls == [treasury.YAHOO_URL]

    def test_falls_back_to_the_second_source(self) -> None:
        urls = []

        def fake_fetch(url: str) -> str:
            urls.append(url)
            if url == treasury.YAHOO_URL:
                raise OSError("yahoo unreachable")
            return SAMPLE_CSV

        assert treasury.fetch_treasury_yield_pct(fake_fetch) == 5.07
        assert urls == [treasury.YAHOO_URL, treasury.FRED_URL]

    def test_all_sources_failing_yields_none(self) -> None:
        def fake_fetch(url: str) -> str:
            raise OSError("down")

        assert treasury.fetch_treasury_yield_pct(fake_fetch) is None
