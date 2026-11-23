"""Tests for the portfolio backtest engine and its input parsing."""

from __future__ import annotations

import datetime as dt

import pytest

from stonks.backtest import (
    monthly_prices,
    run_backtest,
    simulate,
)
from stonks.backtest_view import (
    _portfolio_rows,
    default_settings,
    format_allocation,
    parse_portfolio,
    parse_symbols,
    parse_weights,
)
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


def test_run_backtest_grows_the_benchmark_over_the_same_window(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    months = _months(2020, 24)
    prices = {month: 100.0 * 1.01**index for index, month in enumerate(months)}
    store.cache_set("hist:AAA:10Y:Monthly", prices, 3600)
    store.cache_set("hist:BMB:10Y:Monthly", prices, 3600)

    result = run_backtest(
        store,
        ["AAA"],
        start="2020-05-01",
        end="2021-04-30",
        benchmark="bmb",
    )

    assert "benchmark_error" not in result
    benchmark = result["benchmark"]
    assert benchmark["symbol"] == "BMB"
    assert benchmark["start"] == result["start"] == "2020-05"
    assert benchmark["end"] == result["end"] == "2021-04"
    assert benchmark["final"] == pytest.approx(result["final"])
    assert benchmark["cagr_pct"] == pytest.approx(result["cagr_pct"])


def test_missing_benchmark_does_not_fail_the_portfolio(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.cache_set(
        "hist:AAA:10Y:Monthly",
        {"2020-01": 100.0, "2020-02": 110.0},
        3600,
    )

    result = run_backtest(store, ["AAA"], benchmark="NOPE")

    assert result["total_return_pct"] == pytest.approx(10.0)
    assert "NOPE" in result["benchmark_error"]
    assert "benchmark" not in result


def test_parse_portfolio_rows() -> None:
    assert parse_portfolio(
        [
            {"Symbol": " vuaa ", "Weight %": None},
            {"Symbol": "GOOGL", "Weight %": float("nan")},
        ]
    ) == (["VUAA", "GOOGL"], None)
    assert parse_portfolio(
        [{"Symbol": "VUAA", "Weight %": 60}, {"Symbol": "CROX", "Weight %": 40}]
    ) == (["VUAA", "CROX"], [60.0, 40.0])
    with pytest.raises(ValueError):
        parse_portfolio([])
    with pytest.raises(ValueError):
        parse_portfolio([{"Symbol": "AAA", "Weight %": None}, {"Symbol": "AAA"}])
    with pytest.raises(ValueError):
        parse_portfolio([{"Symbol": "AAA", "Weight %": 60}, {"Symbol": "BBB"}])
    with pytest.raises(ValueError):
        parse_portfolio([{"Symbol": "AAA", "Weight %": -5}])


def test_default_portfolio_is_the_editable_four_symbol_preset() -> None:
    settings = default_settings()
    assert settings["symbols"] == ["VUAA", "GOOGL", "NVDA", "CROX"]
    assert settings["benchmark"] == "VUAA"
    assert settings["weights"] is None


def test_saved_backtests_round_trip(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    assert store.list_backtests() == []

    store.save_backtest("Main", {"symbols": ["VUAA"], "weights": None})
    saved = store.list_backtests()
    assert [item["name"] for item in saved] == ["Main"]
    assert saved[0]["settings"]["symbols"] == ["VUAA"]

    store.save_backtest("Main", {"symbols": ["GOOGL", "NVDA"], "weights": [60, 40]})
    saved = store.list_backtests()
    assert len(saved) == 1
    assert saved[0]["settings"]["weights"] == [60, 40]

    store.delete_backtest("Main")
    assert store.list_backtests() == []


def test_contributions_buy_at_month_zero_and_accumulate() -> None:
    months = _months(2020, 4)
    result = simulate(
        {"A": dict.fromkeys(months, 100.0)},
        {"A": 1.0},
        initial=0.0,
        contributions={"A": 100.0},
        frequency="monthly",
    )
    assert "error" not in result
    assert result["invested"] == 400.0
    assert [point["value"] for point in result["curve"]] == [
        100.0,
        200.0,
        300.0,
        400.0,
    ]
    assert result["cagr_pct"] == pytest.approx(0.0)


def test_contributions_keep_time_weighted_stats_independent_of_deposits() -> None:
    months = _months(2020, 25)
    prices = {
        "A": {
            month: 100.0 if index < 12 else 50.0 for index, month in enumerate(months)
        }
    }
    result = simulate(
        prices,
        {"A": 1.0},
        initial=0.0,
        contributions={"A": 100.0},
        frequency="monthly",
        rebalance="none",
    )
    assert result["max_drawdown_pct"] == pytest.approx(-50.0)
    assert result["cagr_pct"] < 0
    assert result["invested"] == 2500.0


def test_contributions_are_invested_in_full_at_month_zero() -> None:
    months = _months(2020, 2)
    prices = {
        "A": dict.fromkeys(months, 100.0),
        "B": dict.fromkeys(months, 100.0),
    }
    result = simulate(
        prices,
        {"A": 60.0, "B": 40.0},
        initial=0.0,
        contributions={"A": 60.0, "B": 40.0},
        frequency="monthly",
    )
    assert result["curve"][0]["value"] == pytest.approx(100.0)


def test_rebalance_happens_after_contribution() -> None:
    months = _months(2020, 3)
    prices = {
        "A": dict.fromkeys(months, 100.0),
        "B": {month: 100.0 * 1.1**index for index, month in enumerate(months)},
    }
    kwargs = {
        "initial": 0.0,
        "contributions": {"A": 60.0, "B": 40.0},
        "frequency": "monthly",
    }
    drift = simulate(prices, {"A": 60.0, "B": 40.0}, rebalance="none", **kwargs)
    rebalanced = simulate(prices, {"A": 60.0, "B": 40.0}, rebalance="monthly", **kwargs)
    assert rebalanced["final"] < drift["final"]


def test_money_weighted_return_reflects_contribution_timing() -> None:
    months = _months(2020, 13)
    prices = {
        "A": {
            month: 100.0 if index == 0 else 200.0 for index, month in enumerate(months)
        }
    }
    result = simulate(
        prices,
        {"A": 1.0},
        initial=0.0,
        contributions={"A": 100.0},
        frequency="monthly",
    )
    assert result["money_weighted_cagr_pct"] is not None
    assert 0 < result["money_weighted_cagr_pct"] < result["cagr_pct"]
    assert simulate(prices, {"A": 1.0})["money_weighted_cagr_pct"] is None


def test_simulate_rejects_bad_contribution_inputs() -> None:
    prices = {"A": dict.fromkeys(_months(2020, 3), 100.0)}
    assert "error" in simulate(prices, {"A": 1.0}, frequency="weekly")
    assert "error" in simulate(prices, {"A": 1.0}, contributions={"A": -1.0})
    assert "error" in simulate(prices, {"A": 1.0}, initial=0.0)
    assert "error" in simulate(
        prices, {"A": 1.0}, initial=0.0, contributions={"A": 1.0}, frequency="none"
    )


def test_run_backtest_gives_benchmark_the_same_contributions(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    months = _months(2020, 13)
    prices = {month: 100.0 for month in months}
    store.cache_set("hist:AAA:10Y:Monthly", prices, 3600)
    store.cache_set("hist:BMB:10Y:Monthly", prices, 3600)

    result = run_backtest(
        store,
        ["AAA"],
        contributions=[100.0],
        frequency="monthly",
        initial=0.0,
        benchmark="BMB",
    )
    assert "benchmark_error" not in result
    assert result["benchmark"]["final"] == pytest.approx(result["final"])
    assert result["benchmark"]["cagr_pct"] == pytest.approx(result["cagr_pct"])
    assert result["invested"] == 1300.0


def test_run_backtest_rejects_mismatched_contributions(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.cache_set("hist:AAA:10Y:Monthly", {"2020-01": 1.0, "2020-02": 2.0}, 3600)
    assert "error" in run_backtest(store, ["AAA"], contributions=[1.0, 2.0])


def test_format_allocation_for_both_modes() -> None:
    assert (
        format_allocation(
            {
                "allocation_mode": "amount",
                "contributions": {"VUAA": 600.0, "NVDA": 400.0},
            }
        )
        == "VUAA 600 · NVDA 400 per contribution"
    )
    assert (
        format_allocation({"weights": {"VUAA": 60.0, "NVDA": 40.0}})
        == "VUAA 60% · NVDA 40%"
    )


def test_parse_portfolio_amount_mode_requires_every_amount() -> None:
    rows = [
        {"Allocation": "vuaa", "Amount": 600},
        {"Allocation": "NVDA", "Amount": 400},
    ]
    assert parse_portfolio(rows, mode="amount") == (["VUAA", "NVDA"], [600.0, 400.0])
    with pytest.raises(ValueError):
        parse_portfolio(
            [{"Allocation": "VUAA", "Amount": 600}, {"Allocation": "NVDA"}],
            mode="amount",
        )


def test_new_settings_round_trip_and_old_settings_default() -> None:
    settings = default_settings()
    assert settings["allocation_mode"] == "percent"
    assert settings["contribution"] == 0.0
    assert settings["contribution_frequency"] == "monthly"
    rows = _portfolio_rows(settings)
    assert "Allocation" in rows[0]
    legacy = {
        "symbols": ["AAA"],
        "weights": [60.0],
        "benchmark": "",
        "rebalance": "none",
    }
    assert _portfolio_rows(legacy)[0]["Allocation"] == 60.0
