"""Tests for the HedgeFollow largest-buys flag."""

import json

from stonks import hedgefollow

SAMPLE_PAGE = """
<script>
    hf_dt = "v1.1795246664.4rjf9KOi6MJ44gmeGw36XOw9";
    logged_in = 0;
</script>
"""

SAMPLE_PAYLOAD = json.dumps(
    {
        "data": [
            {"symbol": "NVDA", "valBuys": 47237102},
            {"symbol": "be", "valBuys": 3710374},
            {"symbol": None, "valBuys": 10},
            {"symbol": "AAA", "valBuys": None},
            {"symbol": "BBB", "valBuys": 5000},
        ],
        "params": {"requestId": "largest_fund_buys_nl"},
    }
)


class TestParseToken:
    def test_reads_the_data_token(self) -> None:
        assert hedgefollow.parse_token(SAMPLE_PAGE) == (
            "v1.1795246664.4rjf9KOi6MJ44gmeGw36XOw9"
        )

    def test_missing_token_is_none(self) -> None:
        assert hedgefollow.parse_token("<html></html>") is None


class TestRequestBody:
    def test_carries_the_token_and_page_defaults(self) -> None:
        body = hedgefollow.request_body("tok").decode()

        assert "dt=tok" in body
        assert "params%5BrequestId%5D=largest_fund_buys_nl" in body
        assert "params%5Bfilters%5D%5Binstitution_type%5D=hf" in body
        assert f"params%5Blimit_per_page%5D={hedgefollow.LIST_SIZE}" in body
        # Both counters are required, or the endpoint answers 400.
        assert "params%5BfilteredCt%5D=0" in body
        assert "params%5BtotalCt%5D=0" in body


class TestParseBuys:
    def test_returns_dollars_bought_per_symbol(self) -> None:
        buys = hedgefollow.parse_buys(SAMPLE_PAYLOAD)

        assert buys == {
            "NVDA": 47_237_102_000.0,
            "BE": 3_710_374_000.0,
            "BBB": 5_000_000.0,
        }

    def test_unusable_payloads_are_empty(self) -> None:
        assert hedgefollow.parse_buys("not json") == {}
        assert hedgefollow.parse_buys(json.dumps({"data": None})) == {}
        assert hedgefollow.parse_buys(json.dumps({"other": []})) == {}


class TestFetchLargestBuys:
    def test_posts_the_token_from_the_page(self) -> None:
        calls = []

        def fake_fetch(url: str, data: bytes | None = None) -> str:
            calls.append((url, data))
            return SAMPLE_PAGE if data is None else SAMPLE_PAYLOAD

        buys = hedgefollow.fetch_largest_buys(fake_fetch)

        assert list(buys or {}) == ["NVDA", "BE", "BBB"]
        assert calls[0] == (hedgefollow.BUYS_PAGE_URL, None)
        assert calls[1][0] == hedgefollow.REQUEST_URL
        assert b"dt=v1.1795246664" in (calls[1][1] or b"")

    def test_page_without_token_is_none(self) -> None:
        buys = hedgefollow.fetch_largest_buys(lambda url, data=None: "<html></html>")

        assert buys is None

    def test_network_failure_is_none(self) -> None:
        def boom(url: str, data: bytes | None = None) -> str:
            raise OSError("hedgefollow unreachable")

        assert hedgefollow.fetch_largest_buys(boom) is None

    def test_empty_list_is_none(self) -> None:
        def fake_fetch(url: str, data: bytes | None = None) -> str:
            return SAMPLE_PAGE if data is None else json.dumps({"data": []})

        assert hedgefollow.fetch_largest_buys(fake_fetch) is None


class TestApplyFlags:
    def test_marks_listed_and_unlisted_symbols(self) -> None:
        rows = [
            {"symbol": "NVDA"},
            {"symbol": "be"},
            {"symbol": "ZZZZ"},
        ]

        assert hedgefollow.apply_flags(rows, {"NVDA", "BE"}) == 2
        assert [row["hedge_fund_buys"] for row in rows] == [1, 1, 0]
