"""Tests for the Yahoo Finance screener provider."""

import pandas as pd
import pytest

from stonks.yahoo import (
    _cagr_from_series,
    build_screener_query,
    derive_metrics,
    enrich_rows,
    enrich_symbol,
    normalize_quote,
    paginate,
    preset_candidate_rows,
)


def test_map_filter_units():
    q = build_screener_query(
        {"market_cap": {"min": 1000}, "free_cash_flow": {"min": 1}}
    )
    d = q.to_dict()
    assert {"operator": "GT", "operands": ["intradaymarketcap", 1000 * 1e6]} in d[
        "operands"
    ]
    assert {
        "operator": "GT",
        "operands": ["leveredfreecashflow.lasttwelvemonths", 1e6],
    } in d["operands"]


def test_build_query_always_restricts_to_us_equities():
    d = build_screener_query({}).to_dict()
    assert {"operator": "EQ", "operands": ["region", "us"]} in d["operands"]
    assert {"operator": "GT", "operands": ["intradaymarketcap", 0]} in d["operands"]


def test_build_query_skips_unmapped_columns():
    d = build_screener_query({"return_cagr_5y_pct": {"min": 10}}).to_dict()
    assert all("return_cagr_5y_pct" not in str(o) for o in d["operands"])


def test_build_query_scales_debt_to_equity_to_yahoo_units():
    d = build_screener_query({"debt_to_equity": {"max": 1.0}}).to_dict()
    assert {
        "operator": "LT",
        "operands": ["totaldebtequity.lasttwelvemonths", 100.0],
    } in d["operands"]


def test_paginate_fetches_all_pages():
    calls = []

    def fake_screen(query, offset=None, size=None, **kwargs):
        calls.append(offset)
        end = min(offset + size, 251)
        return {
            "total": 251,
            "quotes": [
                {"symbol": f"S{i}", "marketCap": 1e9} for i in range(offset, end)
            ],
        }

    rows = paginate(build_screener_query({}), page_size=250, screen_fn=fake_screen)
    assert calls == [0, 250]
    assert len(rows) == 251


def test_normalize_quote_units():
    row = normalize_quote(
        {
            "symbol": "ZTS",
            "shortName": "Zoetis",
            "exchange": "NYQ",
            "fullExchangeName": "NYSE",
            "currency": "USD",
            "marketCap": 32_826_281_984,
            "regularMarketPrice": 80.79,
            "trailingPE": 13.74,
            "priceToBook": 9.97,
            "bookValue": 8.106,
            "dividendYield": 2.62,
            "epsTrailingTwelveMonths": 5.88,
            "fiftyTwoWeekHigh": 132.49,
            "fiftyTwoWeekLow": 68.77,
            "averageAnalystRating": "2.2 - Buy",
            "beta": 0.9,
        }
    )
    assert row["market_cap"] == pytest.approx(32826.281984)
    assert row["dividend_yield_pct"] == 2.62
    assert row["price"] == 80.79
    assert row["rating"] == "Buy"
    assert row["pe_ratio"] == 13.74
    assert "roic_5y_avg_pct" not in row


def test_cagr_uses_requested_window():
    idx = pd.date_range("2021-01-01", periods=5, freq="YS")
    series = pd.Series([100, 110, 121, 133.1, 146.41], index=idx)
    assert _cagr_from_series(series, 3) == pytest.approx(10.0)


def test_derive_metrics_cagr_and_averages():
    idx = pd.date_range("2011-01-31", "2026-01-31", freq="ME")
    history = pd.DataFrame(
        {"Close": [100 * (1.1 ** (i / 12)) for i in range(len(idx))]}, index=idx
    )
    info = {
        "returnOnAssets": 0.10,
        "returnOnEquity": 0.20,
        "grossMargins": 0.5,
        "operatingMargins": 0.3,
        "debtToEquity": 150.0,
        "freeCashflow": 2e9,
        "heldPercentInsiders": 0.01,
        "dividendYield": 2.5,
    }
    result = derive_metrics(info, history, None, None, None)
    assert result["return_cagr_5y_pct"] == pytest.approx(10.0, abs=0.2)
    assert result["roa_pct"] == 10.0
    assert result["roe_pct"] == 20.0
    assert result["debt_to_equity"] == pytest.approx(1.5)
    assert result["shares_insiders_pct"] == 0.01
    assert result["free_cash_flow"] == pytest.approx(2000.0)


def test_price_cagr_handles_history_starting_at_lookback_boundary():
    # 15y of monthly bars starts just after the exact 15-year cutoff, so
    # asof(target) is NaN. The CAGR must still be computed from the first bar.
    idx = pd.date_range("2011-12-31", "2026-11-30", freq="ME")
    history = pd.DataFrame(
        {"Close": [100 * (1.1 ** (i / 12)) for i in range(len(idx))]}, index=idx
    )
    result = derive_metrics({}, history, None, None, None)
    assert result["return_cagr_15y_pct"] == pytest.approx(10.0, abs=0.5)


def test_derive_metrics_accepts_first_available_financial_row():
    years = pd.to_datetime(["2022-01-01", "2023-01-01", "2024-01-01"])
    financials = pd.DataFrame(
        {"2022": [1e9], "2023": [1.2e9], "2024": [1.4e9]},
        index=pd.Index(["Net Income"], name=""),
    )
    financials.columns = pd.DatetimeIndex(years)
    financials.index.name = None

    result = derive_metrics(None, None, financials, None, None)

    assert result["net_income"] == pytest.approx(1400.0)


def test_derive_metrics_computes_latest_roic():
    years = pd.to_datetime(["2025-01-01", "2024-01-01", "2023-01-01"])
    financials = pd.DataFrame(
        {"2025": [120.0], "2024": [110.0], "2023": [100.0]},
        index=pd.Index(["Net Income"], name=""),
    )
    financials.columns = pd.DatetimeIndex(years)
    financials.index.name = None
    balance_sheet = pd.DataFrame(
        {
            "2025": [220.0, 320.0],
            "2024": [210.0, 310.0],
            "2023": [200.0, 300.0],
        },
        index=pd.Index(["Total Debt", "Total Equity Gross Minority Interest"], name=""),
    )
    balance_sheet.columns = pd.DatetimeIndex(years)
    balance_sheet.index.name = None

    result = derive_metrics(None, None, financials, balance_sheet, None)

    assert result["roic_pct"] == pytest.approx(120 / (220 + 320) * 100)


def test_derive_metrics_computes_3y_revenue_growth():
    years = pd.to_datetime(["2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01"])
    financials = pd.DataFrame(
        {"2022": [100.0], "2023": [110.0], "2024": [121.0], "2025": [133.1]},
        index=pd.Index(["Total Revenue"], name=""),
    )
    financials.columns = pd.DatetimeIndex(years)
    financials.index.name = None

    result = derive_metrics(None, None, financials, None, None)

    assert result["revenue_growth_3y_pct"] == pytest.approx(10.0)


def test_derive_metrics_insufficient_history():
    idx = pd.date_range("2025-01-31", periods=6, freq="ME")
    history = pd.DataFrame({"Close": range(100, 106)}, index=idx)
    result = derive_metrics({}, history, None, None, None)
    for key in (
        "return_cagr_5y_pct",
        "return_cagr_10y_pct",
        "return_cagr_15y_pct",
        "roa_5y_avg_pct",
        "roe_5y_avg_pct",
        "roic_5y_avg_pct",
    ):
        assert result[key] is None


def test_enrich_symbol_retries_transient_failure(monkeypatch):
    class FakeTicker:
        def __init__(self):
            self.attempts = 0

        @property
        def info(self):
            self.attempts += 1
            if self.attempts < 3:
                raise RuntimeError("429")
            return {"grossMargins": 0.5}

        def history(self, **kwargs):
            return None

        @property
        def financials(self):
            return None

        @property
        def balance_sheet(self):
            return None

        @property
        def cashflow(self):
            return None

    ticker = FakeTicker()
    monkeypatch.setattr("stonks.yahoo.yf.Ticker", lambda symbol: ticker)
    monkeypatch.setattr("stonks.yahoo.time.sleep", lambda delay: None)

    result = enrich_symbol("RETRY")

    assert ticker.attempts == 3
    assert result["gross_margin_pct"] == 50.0


def test_enrich_symbol_handles_missing_ticker_data(monkeypatch):
    class FakeTicker:
        info = None

        def history(self, **kwargs):
            raise RuntimeError("no history")

    monkeypatch.setattr("stonks.yahoo.yf.Ticker", lambda symbol: FakeTicker())
    result = enrich_symbol("NEWCO")
    assert result["symbol"] == "NEWCO"
    assert result["free_cash_flow"] is None


def test_preset_candidate_rows_deduplicates():
    presets = [
        {"filters": {"market_cap": {"min": 1000}}},
        {"filters": {"roe_pct": {"min": 15}, "return_cagr_5y_pct": {"min": 10}}},
    ]
    seen = []

    def fake_screen(query, offset=None, size=None, **kwargs):
        seen.append(query.to_dict())
        symbols = ["AAA", "BBB"] if len(seen) == 1 else ["BBB", "CCC"]
        return {"total": len(symbols), "quotes": [{"symbol": s} for s in symbols]}

    rows = preset_candidate_rows(presets, page_size=250, screen_fn=fake_screen)
    assert [r["symbol"] for r in rows] == ["AAA", "BBB", "CCC"]
    assert len(seen) == 2


def test_enrich_rows_only_fetches_missing_columns():
    calls = []

    def fake_enrich(symbol):
        calls.append(symbol)
        return {"roic_5y_avg_pct": 12.0}

    rows = [{"symbol": "AAA", "roic_5y_avg_pct": 9.0}, {"symbol": "BBB"}]
    result = enrich_rows(rows, {"roic_5y_avg_pct"}, enrich_fn=fake_enrich)
    assert calls == ["BBB"]
    assert result[0]["roic_5y_avg_pct"] == 9.0
    assert result[1]["roic_5y_avg_pct"] == 12.0


def test_screen_does_not_read_missing_fundamentals():
    def fake_screen(query, offset=None, size=None, **kwargs):
        return {"total": 1, "quotes": [{"symbol": "AAA", "returnontotalcapital": 15}]}

    rows = preset_candidate_rows(
        [{"filters": {"roic_pct": {"min": 10}}}], screen_fn=fake_screen
    )
    assert "roic_pct" not in rows[0]


def test_build_screener_query_ors_enum_values():
    query = build_screener_query({"exchange": {"values": ["NYQ", "NMS"]}})
    operands = query.to_dict()["operands"]
    or_operand = next(o for o in operands if o["operator"] == "OR")
    assert {"operator": "EQ", "operands": ["exchange", "NYQ"]} in or_operand["operands"]
    assert {"operator": "EQ", "operands": ["exchange", "NMS"]} in or_operand["operands"]


def test_paginate_skips_quotes_without_symbol():
    def fake_screen(query, offset=None, size=None, **kwargs):
        return {
            "total": 2,
            "quotes": [{"marketCap": 1e9}, {"symbol": "AAA", "marketCap": 2e9}],
        }

    rows = paginate(build_screener_query({}), page_size=250, screen_fn=fake_screen)
    assert [row["symbol"] for row in rows] == ["AAA"]


def test_normalize_quote_maps_quote_type():
    row = normalize_quote({"symbol": "AAA", "quoteType": "EQUITY"})
    assert row["type"] == "EQUITY"


def test_derive_metrics_populates_ui_columns():
    info = {
        "industry": "Software",
        "targetMeanPrice": 110.0,
        "currentPrice": 100.0,
        "sharesOutstanding": 1.0,
    }
    financials = pd.DataFrame(
        {
            "2021": [100, 80],
            "2022": [110, 88],
            "2023": [121, 96.8],
            "2024": [133, 106.48],
            "2025": [146, 117.128],
        },
        index=["Total Revenue", "Basic EPS"],
    )
    balance_sheet = pd.DataFrame(
        {"2024": [100, 100, 20], "2025": [120, 120, 30]},
        index=["Total Assets", "Total Equity", "Long Term Debt"],
    )
    cashflow = pd.DataFrame({"2024": [20], "2025": [25]}, index=["Free Cash Flow"])

    result = derive_metrics(info, None, financials, balance_sheet, cashflow)

    assert result["industry"] == "Software"
    assert result["pt_upside_pct"] == pytest.approx(10.0)
    assert result["eps_growth_3y_pct"] == pytest.approx(10.0, abs=0.5)
    assert result["fcf_margin_pct"] == pytest.approx(25 / 146 * 100)
    assert result["free_cash_flow_per_share"] == 25.0
    assert result["revenue_per_share"] == 146.0
    assert result["long_term_debt_to_equity"] == pytest.approx(30 / 120)
    assert result["asset_turnover"] == pytest.approx(146 / 110)


def test_enrich_rows_merges_all_derived_values():
    def fake_enrich(symbol):
        return {"symbol": symbol, "industry": "Software", "pt_upside_pct": 10.0}

    rows = enrich_rows([{"symbol": "AAA"}], {"roe_pct"}, enrich_fn=fake_enrich)
    assert rows[0]["industry"] == "Software"
    assert rows[0]["pt_upside_pct"] == 10.0
