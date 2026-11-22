"""Tests for the portfolio backtest engine and its input parsing."""

from __future__ import annotations

import datetime as dt

import pytest

from stonks.backtest import (
    monthly_prices,
    run_backtest,
    simulate,
)
from stonks.backtest_view import parse_symbols, parse_weights
from stonks.store import SQLiteStore


def _months(start_year: int, count: int) -> list[str]:
    months = []
    year, month = start_year, 1
    for _ in range(count):
        months.append(f"{year}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def test_simulate_annual_rebalance_rebalances_once_a_year() -> None:
    months = _months(2020, 25)
    prices = {
        "GROW": {month: 100.0 * 1.01**index for index, month in enumerate(months)},
        "FLAT": dict.fromkeys(months, 100.0),
    }
    annual = simulate(prices, {"GROW": 60, "FLAT": 40}, rebalance="annual")
    none = simulate(prices, {"GROW": 60, "FLAT": 40}, rebalance="none")
    assert "error" not in annual
    assert annual["stdev_pct"] is not None
    # Rebalancing into a flat asset drags a compounding position down.
    assert annual["total_return_pct"] < none["total_return_pct"]


def test_simulate_monthly_matches_monthly_compounding() -> None:
    months = _months(2020, 13)
    prices = {
        "A": {month: 100.0 + index * 5 for index, month in enumerate(months)},
        "B": {month: 100.0 + index * 2 for index, month in enumerate(months)},
    }
    result = simulate(prices, {"A": 50, "B": 50}, rebalance="monthly")
    expected = 1.0
    for index in range(1, len(months)):
        a = prices["A"][months[index]] / prices["A"][months[index - 1]] - 1
        b = prices["B"][months[index]] / prices["B"][months[index - 1]] - 1
        expected *= 1 + 0.5 * a + 0.5 * b
    assert result["total_return_pct"] == pytest.approx((expected - 1) * 100, abs=1e-9)


def test_simulate_uses_prior_december_for_yearly_returns() -> None:
    prices = {
        "A": {
            "2020-12": 100.0,
            "2021-06": 110.0,
            "2021-12": 120.0,
            "2022-06": 108.0,
            "2022-12": 96.0,
        }
    }
    result = simulate(prices, {"A": 100})
    yearly = {row["year"]: row["return_pct"] for row in result["yearly"]}
    assert yearly["2021"] == pytest.approx(20.0)
    assert yearly["2022"] == pytest.approx(-20.0)
    assert result["best_year_pct"] == pytest.approx(20.0)
    assert result["worst_year_pct"] == pytest.approx(-20.0)


def test_simulate_reports_missing_overlap_and_bad_input() -> None:
    assert "error" in simulate({}, {})
    assert "error" in simulate({"A": {"2020-01": 1.0}}, {"A": 1})
    assert "error" in simulate({"A": {"2020-01": 1.0, "2020-02": 2.0}}, {"A": 0})
    assert "error" in simulate(
        {"A": {"2020-01": 1.0, "2020-02": 2.0}}, {"A": 1}, rebalance="weekly"
    )


def test_simulate_caps_drawdown() -> None:
    prices = {
        "A": {"2020-01": 100.0, "2020-02": 150.0, "2020-03": 90.0, "2020-04": 120.0}
    }
    result = simulate(prices, {"A": 100})
    assert result["max_drawdown_pct"] == pytest.approx(-40.0)


def test_monthly_prices_prefers_adjusted_close(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    payload = {
        "data": [
            {"t": "2020-02-01", "c": 50.0, "a": 45.0},
            {"t": "2020-01-01", "c": 40.0, "a": 36.0},
            {"t": "2020-03-01", "c": 55.0},
        ]
    }
    prices = monthly_prices(store, "aaa", fetch=lambda url: payload)
    assert prices == {"2020-01": 36.0, "2020-02": 45.0, "2020-03": 55.0}
    assert store.cache_get("hist:AAA:10Y:Monthly") == prices


def test_run_backtest_slices_the_window_and_reports_weights(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    months = _months(2020, 30)
    store.cache_set("hist:AAA:10Y:Monthly", dict.fromkeys(months, 100.0), 3600)
    store.cache_set("hist:BBB:10Y:Monthly", dict.fromkeys(months, 200.0), 3600)

    result = run_backtest(
        store,
        ["aaa", "BBB", "aaa"],
        [3, 1],
        start="2021-03-15",
        end=dt.date(2022, 6, 30).isoformat(),
    )
    assert result["symbols"] == ["AAA", "BBB"]
    assert result["start"] == "2021-03"
    assert result["end"] == "2022-06"
    assert result["weights"] == pytest.approx({"AAA": 75.0, "BBB": 25.0})


def test_run_backtest_rejects_mismatched_weights_and_unknown_symbol(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.cache_set("hist:AAA:10Y:Monthly", {"2020-01": 1.0, "2020-02": 2.0}, 3600)
    assert "error" in run_backtest(store, ["AAA"], [1, 2])
    assert "error" in run_backtest(store, ["ZZZ"])
    assert "error" in run_backtest(store, [])
    assert "error" in run_backtest(store, ["AAA"], [])


def test_parse_symbols_and_weights() -> None:
    assert parse_symbols(" spy, BND  bnd;qqq ") == ["SPY", "BND", "QQQ"]
    assert parse_weights("60, 40%") == [60.0, 40.0]
    assert parse_weights("  ") is None
    with pytest.raises(ValueError):
        parse_weights("sixty")
    with pytest.raises(ValueError):
        parse_weights("60, -40")
