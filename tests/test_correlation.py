import pytest

from stonks import correlation, portfolio
from stonks.store import SQLiteStore


def _summary(symbols=("AAA",)):
    positions = [
        {"symbol": sym, "quantity": 1, "price": 100.0, "currency": "USD"}
        for sym in symbols
    ]
    quotes = {
        sym: {"price": 100.0, "currency": "USD", "description": sym} for sym in symbols
    }
    return portfolio.build_portfolio_summary(positions, quotes, {}, {"USD": 1.0})


def test_portfolio_correlation_returns_pearson_value(tmp_path, monkeypatch) -> None:
    store = SQLiteStore(db_path=tmp_path / "corr.db")
    positions = [{"symbol": "AAA", "quantity": 1, "price": 100.0, "currency": "USD"}]
    prices = {f"2025-{month:02d}": float(100 + month % 2) for month in range(1, 15)}
    monkeypatch.setattr("stonks.correlation.monthly_prices", lambda *a, **k: prices)
    value = correlation.portfolio_correlation(store, "BBB", _summary(), positions)
    assert value == pytest.approx(1.0)


def test_portfolio_correlation_returns_none_without_enough_overlap(
    tmp_path, monkeypatch
) -> None:
    store = SQLiteStore(db_path=tmp_path / "corr.db")
    positions = [{"symbol": "AAA", "quantity": 1, "price": 100.0, "currency": "USD"}]
    few_prices = {f"2025-{month:02d}": float(100 + month) for month in range(1, 4)}
    monkeypatch.setattr("stonks.correlation.monthly_prices", lambda *a, **k: few_prices)
    assert (
        correlation.portfolio_correlation(store, "BBB", _summary(), positions) is None
    )


def test_portfolio_correlation_cache_invalidates_when_holdings_change(
    tmp_path, monkeypatch
) -> None:
    store = SQLiteStore(db_path=tmp_path / "corr.db")
    calls = []
    payload = {
        "data": [
            {"t": f"2025-{month:02d}-01", "c": 100 + month, "a": 100 + month}
            for month in range(1, 15)
        ]
    }

    def fake_prices(_store, symbol, **kwargs):
        calls.append(symbol)
        return {row["t"][:7]: row["c"] for row in payload["data"]}

    monkeypatch.setattr("stonks.correlation.monthly_prices", fake_prices)
    first = [{"symbol": "AAA", "quantity": 1, "price": 100.0, "currency": "USD"}]
    correlation.portfolio_correlation(store, "BBB", _summary(), first)
    count_after_first = len(calls)
    correlation.portfolio_correlation(store, "BBB", _summary(), first)
    assert len(calls) == count_after_first

    changed = [{"symbol": "AAA", "quantity": 9, "price": 100.0, "currency": "USD"}]
    correlation.portfolio_correlation(store, "BBB", _summary(), changed)
    assert len(calls) > count_after_first


def test_portfolio_correlation_factor_is_high_when_prices_move_together(
    tmp_path, monkeypatch
) -> None:
    store = SQLiteStore(db_path=tmp_path / "corr.db")
    months = [f"2025-{month:02d}" for month in range(1, 15)]
    rising = {month: 100.0 * 1.01**index for index, month in enumerate(months)}
    prices = {
        "AAA": rising,
        "BBB": {month: value * 2 for month, value in rising.items()},
    }
    monkeypatch.setattr(
        "stonks.correlation.monthly_prices",
        lambda _store, symbol, **kwargs: prices[symbol],
    )

    value = correlation.portfolio_correlation_factor(
        store, ["AAA", "BBB"], [50.0, 50.0]
    )

    assert value == pytest.approx(1.0)


def test_portfolio_correlation_factor_needs_two_symbols_and_enough_overlap(
    tmp_path, monkeypatch
) -> None:
    store = SQLiteStore(db_path=tmp_path / "corr.db")
    prices = {
        "AAA": {f"2025-{month:02d}": 100.0 + month for month in range(1, 15)},
        "BBB": {f"2025-{month:02d}": 200.0 + month for month in range(1, 4)},
    }
    monkeypatch.setattr(
        "stonks.correlation.monthly_prices",
        lambda _store, symbol, **kwargs: prices[symbol],
    )

    assert correlation.portfolio_correlation_factor(store, ["AAA"], [100.0]) is None
    assert (
        correlation.portfolio_correlation_factor(store, ["AAA", "BBB"], [50.0, 50.0])
        is None
    )
