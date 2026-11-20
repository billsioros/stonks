"""Tests for the StockAnalysis.com bulk screener provider."""

import json

import pytest

from stonks import stockanalysis

UNIVERSE_PAYLOAD = {
    "status": 200,
    "data": {
        "count": 2,
        "columns": ["s", "n", "marketCap", "price", "change", "industry", "volume"],
        "rows": [
            [
                "AAPL",
                "Apple Inc.",
                5_074_783_276_220,
                349.21,
                -0.92,
                "Consumer Electronics",
                40_906_860,
            ],
            [
                "MSFT",
                "Microsoft Corporation",
                3_700_472_745_262,
                498.3,
                -1.78,
                "Software - Infrastructure",
                29_350_637,
            ],
        ],
    },
}

METRICS_PAYLOAD = {
    "status": 200,
    "data": {
        "data": {
            "AAPL": {
                "marketCap": 5_074_783_276_220,
                "peRatio": 38.88753,
                "dividendYield": 0.3093,
                "grossMargin": 46.197,
                "roe": 160.834,
                "debtEquity": 0.84286,
                "fcf": 136_056_000_000,
                "netIncome": 132_175_000_000,
                "sharesInsiders": 0.060866,
                "shortFloat": 0.99803,
                "analystRatings": "Buy",
                "priceTargetChange": 5.5,
                "eps": 8.98,
                "price": 349.21,
                "epsGrowth5Y": 9.86584,
                "epsGrowth10Y": 15.764,
                "exchange": "NASDAQ",
                "priceCurrency": "USD",
                "industry": "ignored because initial wins",
                "unmappedField": "ignore me",
            },
            "MSFT": {
                "marketCap": 3_700_472_745_262,
                "exchange": "NYSE",
                "fcf": None,
                "netIncome": 142_631_000_000,
                "sharesInsiders": 0.031794,
            },
            "ORPHAN": {"marketCap": 1.0},
        }
    },
}


def test_fetch_universe_maps_columns_to_local_fields(monkeypatch):
    urls = []

    def fake_fetch(url):
        urls.append(url)
        return UNIVERSE_PAYLOAD

    monkeypatch.setattr(stockanalysis, "fetch_json", fake_fetch)

    rows = stockanalysis.fetch_universe()

    assert urls == [stockanalysis.INITIAL_URL]
    assert rows[0] == {
        "symbol": "AAPL",
        "description": "Apple Inc.",
        "industry": "Consumer Electronics",
    }
    assert rows[1]["symbol"] == "MSFT"


def test_fetch_metrics_requests_all_data_point_ids_without_symbol(monkeypatch):
    urls = []

    def fake_fetch(url):
        urls.append(url)
        return METRICS_PAYLOAD

    monkeypatch.setattr(stockanalysis, "fetch_json", fake_fetch)

    metrics = stockanalysis.fetch_metrics()

    assert metrics is METRICS_PAYLOAD["data"]["data"]
    assert len(urls) == 1
    requested = urls[0].split("ids=", 1)[1].split("+")
    assert "s" not in requested
    assert set(stockanalysis.DATA_POINT_IDS) <= set(requested)
    assert {"marketCap", "fcf", "netIncome", "sharesInsiders"} <= set(requested)


def test_build_rows_converts_units_and_maps_columns():
    rows = stockanalysis.build_rows(
        [
            {"symbol": "AAPL", "description": "Apple Inc.", "industry": "Hardware"},
            {"symbol": "MSFT", "description": "Microsoft", "industry": "Software"},
            {"symbol": "MISSING", "description": "No metrics", "industry": None},
        ],
        METRICS_PAYLOAD["data"]["data"],
    )

    aapl = next(row for row in rows if row["symbol"] == "AAPL")
    assert aapl["description"] == "Apple Inc."
    assert aapl["industry"] == "Hardware"
    assert aapl["market_cap"] == 5_074_783_276_220
    assert aapl["free_cash_flow"] == 136_056.0
    assert aapl["net_income"] == 132_175.0
    assert aapl["shares_insiders_pct"] == 0.00060866
    assert aapl["dividend_yield_pct"] == 0.3093
    assert aapl["debt_to_equity"] == 0.84286
    assert aapl["short_pct"] == 0.99803
    assert aapl["rating"] == "Buy"
    assert aapl["pt_upside_pct"] == 5.5
    assert aapl["dcf_fair_value"] is not None
    assert aapl["dcf_upside_pct"] is not None
    assert aapl["lynch_fair_value"] == 8.98 * 9.86584
    assert aapl["exchange"] == "NMS"
    assert aapl["currency"] == "USD"
    assert "unmappedField" not in aapl

    msft = next(row for row in rows if row["symbol"] == "MSFT")
    assert msft["exchange"] == "NYQ"
    assert msft["free_cash_flow"] is None
    assert msft["net_income"] == 142_631.0
    assert msft["shares_insiders_pct"] == 0.00031794
    # No EPS growth data means no valuation must be invented.
    assert msft["dcf_fair_value"] is None
    assert msft["dcf_upside_pct"] is None
    assert msft["lynch_fair_value"] is None

    assert {row["symbol"] for row in rows} == {"AAPL", "MSFT"}


def test_build_rows_applies_the_supplied_discount_rate():
    universe = [{"symbol": "AAPL", "description": "Apple Inc.", "industry": "H"}]
    metrics = METRICS_PAYLOAD["data"]["data"]

    low = stockanalysis.build_rows(universe, metrics, 0.11)[0]["dcf_fair_value"]
    high = stockanalysis.build_rows(universe, metrics, 0.12)[0]["dcf_fair_value"]

    assert low is not None and high is not None
    assert low > high


def test_fetch_rows_calls_both_endpoints_and_merges(monkeypatch):
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return UNIVERSE_PAYLOAD if "initial" in url else METRICS_PAYLOAD

    monkeypatch.setattr(stockanalysis, "fetch_json", fake_fetch)
    # The default path would hit the live Treasury feed.
    monkeypatch.setattr(stockanalysis, "fetch_treasury_yield_pct", lambda: 5.07)

    rows = stockanalysis.fetch_rows()

    assert len(calls) == 2
    assert len(rows) == 2
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["free_cash_flow"] == 136_056.0
    # 5.07 -> ceil + 6% = 12% discount rate.
    assert rows[0]["dcf_fair_value"] == pytest.approx(
        stockanalysis.build_rows(  # same inputs, explicit rate
            stockanalysis.fetch_universe(fake_fetch),
            METRICS_PAYLOAD["data"]["data"],
            0.12,
        )[0]["dcf_fair_value"]
    )


def test_fetch_json_retries_transient_http_error(monkeypatch):
    payload = {"status": 200}
    raw = json.dumps(payload).encode()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return raw

    attempts = []

    def fake_urlopen(url, timeout=None):
        attempts.append(url)
        if len(attempts) == 1:
            raise OSError("temporary network error")
        return FakeResponse()

    monkeypatch.setattr(stockanalysis.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(stockanalysis.time, "sleep", lambda seconds: None)

    assert stockanalysis.fetch_json("https://example.test/data") == payload
    assert len(attempts) == 2


def test_fetch_json_raises_after_all_attempts(monkeypatch):
    attempts = []

    def fake_urlopen(url, timeout=None):
        attempts.append(url)
        raise OSError("down")

    monkeypatch.setattr(stockanalysis.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(stockanalysis.time, "sleep", lambda seconds: None)

    try:
        stockanalysis.fetch_json("https://example.test/data")
    except OSError:
        pass
    else:
        raise AssertionError("fetch_json should propagate the final error")

    assert len(attempts) == stockanalysis.REQUEST_ATTEMPTS
