import pytest

from stonks import portfolio
from stonks.store import SQLiteStore


def test_validate_lot_rejects_unsupported_currency() -> None:
    with pytest.raises(ValueError, match="USD or EUR"):
        portfolio.validate_lot("AAA", 1, 10.0, "GBP")
    portfolio.validate_lot("aaa", 0.5, 12.0, "eur")


def test_parse_fx_rate_reads_frankfurter_payload() -> None:
    assert portfolio.parse_fx_rate({"rates": {"USD": 1.08}}) == pytest.approx(1.08)
    assert portfolio.parse_fx_rate({"rates": {"USD": -1}}) is None
    assert portfolio.parse_fx_rate({"rates": {}}) is None


def test_usd_rate_falls_back_to_stale_rate(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "fx.db")
    store.cache_set(portfolio.FX_CACHE_KEY, 1.10, ttl_seconds=-1)

    def boom(url: str) -> dict:
        raise OSError("offline")

    assert portfolio.usd_rate(store, "EUR", fetch=boom) == (1.10, True)
    assert portfolio.usd_rate(store, "USD") == (1.0, False)


def test_usd_rate_returns_none_when_no_rate_exists(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "fx.db")

    def boom(url: str) -> dict:
        raise OSError("offline")

    assert portfolio.usd_rate(store, "EUR", fetch=boom) == (None, False)


def test_summary_excludes_a_holding_without_a_price() -> None:
    positions = [{"symbol": "AAA", "quantity": 2, "price": 10.0, "currency": "USD"}]
    summary = portfolio.build_portfolio_summary(
        positions, {"AAA": {"price": None, "currency": "USD"}}, {}, {"USD": 1.0}
    )
    holding = summary.holdings[0]
    assert holding.last is None
    assert holding.market_usd is None
    assert summary.total_value_usd == 0.0
    assert summary.excluded_symbols == ("AAA",)


def test_summary_converts_mixed_currency_lots() -> None:
    positions = [
        {"symbol": "VUAA", "quantity": 10, "price": 100.0, "currency": "EUR"},
        {"symbol": "VUAA", "quantity": 5, "price": 120.0, "currency": "USD"},
    ]
    rates = {"USD": 1.0, "EUR": 1.2}
    summary = portfolio.build_portfolio_summary(
        positions,
        {"VUAA": {"price": 110.0, "currency": "EUR", "description": "S&P 500"}},
        {"VUAA": 100.0},
        rates,
    )
    holding = summary.holdings[0]
    assert holding.quantity == 15
    assert holding.cost_native == pytest.approx(1500.0)
    assert holding.cost_usd == pytest.approx(1800.0)
    assert holding.market_native == pytest.approx(1650.0)
    assert holding.market_usd == pytest.approx(1980.0)
    assert holding.unrealized_usd == pytest.approx(180.0)
    assert holding.change_pct == pytest.approx(10.0)
    assert summary.total_value_usd == pytest.approx(1980.0)


def test_portfolio_snapshot_uses_cached_daily_history(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "snap.db")
    store.replace_stocks([{"symbol": "AAA", "price": 110.0, "currency": "USD"}])
    store.add_position("AAA", 2, 100.0, "USD")
    store.cache_set(
        "hist:AAA:1Y",
        [
            {"date": "2026-11-24", "close": 100.0},
            {"date": "2026-11-25", "close": 110.0},
        ],
        ttl_seconds=60,
    )
    summary, stale = portfolio.portfolio_snapshot(store)
    assert stale == []
    assert summary.holdings[0].last == 110.0
    assert summary.holdings[0].daily_pnl_usd == pytest.approx(20.0)
    assert summary.total_value_usd == pytest.approx(220.0)


def test_backtest_allocation_normalises_to_percent() -> None:
    positions = [
        {"symbol": "AAA", "quantity": 1, "price": 100.0, "currency": "USD"},
        {"symbol": "BBB", "quantity": 3, "price": 100.0, "currency": "USD"},
    ]
    quotes = {
        "AAA": {"price": 100.0, "currency": "USD"},
        "BBB": {"price": 100.0, "currency": "USD"},
    }
    summary = portfolio.build_portfolio_summary(positions, quotes, {}, {"USD": 1.0})
    assert portfolio.backtest_allocation(summary) == (["AAA", "BBB"], [25.0, 75.0])


def test_summary_excludes_missing_price_from_usd_totals() -> None:
    positions = [
        {"symbol": "AAA", "quantity": 2, "price": 10.0, "currency": "USD"},
        {"symbol": "BBB", "quantity": 1, "price": 100.0, "currency": "USD"},
    ]
    quotes = {
        "AAA": {"price": None, "currency": "USD"},
        "BBB": {"price": 120.0, "currency": "USD"},
    }
    summary = portfolio.build_portfolio_summary(positions, quotes, {}, {"USD": 1.0})
    assert summary.excluded_symbols == ("AAA",)
    assert summary.total_cost_usd == pytest.approx(100.0)
    assert summary.total_value_usd == pytest.approx(120.0)
    assert summary.unrealized_pnl_usd == pytest.approx(20.0)
    assert summary.unrealized_pct == pytest.approx(20.0)
    assert portfolio.backtest_allocation(summary) == (["BBB"], [100.0])


def test_summary_clears_usd_fields_when_lot_rate_missing() -> None:
    positions = [
        {"symbol": "AAA", "quantity": 2, "price": 10.0, "currency": "EUR"},
        {"symbol": "BBB", "quantity": 1, "price": 100.0, "currency": "USD"},
    ]
    quotes = {
        "AAA": {"price": 12.0, "currency": "USD"},
        "BBB": {"price": 110.0, "currency": "USD"},
    }
    summary = portfolio.build_portfolio_summary(
        positions, quotes, {"AAA": 10.0}, {"USD": 1.0}
    )
    holding = summary.holdings[0]
    assert holding.last == 12.0
    for field in (
        "cost_native",
        "cost_usd",
        "avg_price",
        "market_native",
        "market_usd",
        "daily_pnl_native",
        "daily_pnl_usd",
        "unrealized_native",
        "unrealized_usd",
    ):
        assert getattr(holding, field) is None, field
    assert summary.excluded_symbols == ("AAA",)
    assert summary.total_cost_usd == pytest.approx(100.0)
    assert summary.total_value_usd == pytest.approx(110.0)
    assert portfolio.backtest_allocation(summary) == (["BBB"], [100.0])


def test_summary_keeps_valuation_without_prior_close() -> None:
    positions = [{"symbol": "AAA", "quantity": 2, "price": 100.0, "currency": "USD"}]
    quotes = {"AAA": {"price": 110.0, "currency": "USD"}}
    summary = portfolio.build_portfolio_summary(positions, quotes, {}, {"USD": 1.0})
    holding = summary.holdings[0]
    assert holding.change_pct is None
    assert holding.daily_pnl_native is None
    assert holding.daily_pnl_usd is None
    assert summary.excluded_symbols == ()
    assert summary.total_value_usd == pytest.approx(220.0)
    assert summary.daily_pnl_usd is None
    assert portfolio.backtest_allocation(summary) == (["AAA"], [100.0])


def test_summary_daily_total_is_available_only_with_complete_history() -> None:
    positions = [
        {"symbol": "AAA", "quantity": 2, "price": 100.0, "currency": "USD"},
        {"symbol": "BBB", "quantity": 1, "price": 100.0, "currency": "USD"},
    ]
    quotes = {
        "AAA": {"price": 110.0, "currency": "USD"},
        "BBB": {"price": 120.0, "currency": "USD"},
    }
    rates = {"USD": 1.0}

    missing = portfolio.build_portfolio_summary(positions, quotes, {}, rates)
    assert all(h.daily_pnl_usd is None for h in missing.holdings)
    assert missing.daily_pnl_usd is None

    partial = portfolio.build_portfolio_summary(
        positions, quotes, {"AAA": 100.0}, rates
    )
    assert partial.holdings[0].daily_pnl_usd == pytest.approx(20.0)
    assert partial.holdings[1].daily_pnl_usd is None
    assert partial.daily_pnl_usd is None

    complete = portfolio.build_portfolio_summary(
        positions, quotes, {"AAA": 100.0, "BBB": 100.0}, rates
    )
    assert complete.daily_pnl_usd == pytest.approx(40.0)
