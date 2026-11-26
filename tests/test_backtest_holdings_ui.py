import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from stonks import app, backtest_view
from stonks.portfolio import build_portfolio_summary
from stonks.store import SQLiteStore


@pytest.fixture(autouse=True)
def _clear_resource_cache_after_each_test() -> None:
    yield
    st.cache_resource.clear()


def _summary() -> object:
    positions = [
        {"symbol": "AAA", "quantity": 1, "price": 100.0, "currency": "USD"},
        {"symbol": "BBB", "quantity": 3, "price": 100.0, "currency": "USD"},
    ]
    quotes = {
        "AAA": {"price": 100.0, "currency": "USD"},
        "BBB": {"price": 100.0, "currency": "USD"},
    }
    return build_portfolio_summary(positions, quotes, {}, {"USD": 1.0})


def test_holdings_settings_uses_market_value_weights() -> None:
    settings = backtest_view.holdings_settings_from_summary(_summary())
    assert settings is not None
    assert settings["symbols"] == ["AAA", "BBB"]
    assert settings["weights"] == [25.0, 75.0]
    assert settings["allocation_mode"] == "percent"


def test_holdings_settings_skips_unpriced_holdings() -> None:
    summary = build_portfolio_summary(
        [{"symbol": "AAA", "quantity": 1, "price": 10.0, "currency": "USD"}],
        {"AAA": {"price": None, "currency": "USD"}},
        {},
        {"USD": 1.0},
    )
    assert backtest_view.holdings_settings_from_summary(summary) is None


def test_run_configured_backtest_uses_settings(monkeypatch) -> None:
    seen = {}

    def fake_run(store, symbols, weights, **kwargs):
        seen.update(symbols=symbols, weights=weights, kwargs=kwargs)
        return {
            "symbols": symbols,
            "weights": dict(zip(symbols, weights)),
            "yearly": {},
        }

    monkeypatch.setattr(backtest_view, "run_backtest", fake_run)
    settings = backtest_view.default_settings()
    settings.update(symbols=["AAA"], weights=[100.0], benchmark="")

    result = backtest_view.run_configured_backtest(object(), settings)

    assert result["allocation_mode"] == "percent"
    assert seen["symbols"] == ["AAA"]
    assert seen["kwargs"]["benchmark"] is None
    assert seen["kwargs"]["rebalance"] == "annual"


def test_backtest_tab_keeps_existing_session_settings(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "bt.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks([{"symbol": "AAA", "price": 100.0, "currency": "USD"}])
    seeded.add_position("AAA", 1, 100.0, "USD")
    real_init = SQLiteStore.__init__

    def _init(self, *args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(SQLiteStore, "__init__", _init)
    monkeypatch.setattr(app, "get_store", lambda: SQLiteStore(db_path=db_path))
    st.cache_resource.clear()
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.session_state[backtest_view._SETTINGS_KEY] = {
        "symbols": ["ZZZ"],
        "weights": None,
    }
    at.run()

    assert not at.exception
    assert at.session_state[backtest_view._SETTINGS_KEY]["symbols"] == ["ZZZ"]


def test_default_settings_include_both_benchmarks() -> None:
    assert backtest_view.default_settings()["benchmark"] == "VUAA, QQQ"


def test_run_configured_backtest_records_correlation_factor(monkeypatch) -> None:
    def fake_run(store, symbols, weights, **kwargs):
        return {
            "symbols": symbols,
            "weights": dict(zip(symbols, weights)),
            "yearly": {},
        }

    monkeypatch.setattr(backtest_view, "run_backtest", fake_run)
    monkeypatch.setattr(
        backtest_view, "portfolio_correlation_factor", lambda *a, **k: 0.85
    )
    settings = backtest_view.default_settings()
    settings.update(symbols=["AAA", "BBB"], weights=[50.0, 50.0])

    result = backtest_view.run_configured_backtest(object(), settings)

    assert result["correlation_factor"] == 0.85


def test_backtest_result_shows_correlation_pill() -> None:
    from stonks.backtest import simulate

    result = simulate(
        {"AAA": {"2025-01": 100.0, "2025-02": 110.0}},
        {"AAA": 1.0},
        initial=1000.0,
    )
    result.update(
        {
            "symbols": ["AAA"],
            "weights": {"AAA": 100.0},
            "rebalance": "none",
            "allocation_mode": "percent",
            "contributions": None,
            "correlation_factor": 0.85,
        }
    )
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.session_state[backtest_view._RESULT_KEY] = result
    at.run()

    assert not at.exception
    assert any("Portfolio correlation" in str(md.value) for md in at.markdown)


def test_backtest_defaults_to_vuaa_and_qqq(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "bt.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks([{"symbol": "AAA", "price": 100.0, "currency": "USD"}])
    real_init = SQLiteStore.__init__

    def _init(self, *args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(SQLiteStore, "__init__", _init)
    monkeypatch.setattr(app, "get_store", lambda: SQLiteStore(db_path=db_path))
    st.cache_resource.clear()
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()

    assert not at.exception
    field = next(item for item in at.text_input if item.label == "Benchmarks")
    assert field.value == "VUAA, QQQ"


def test_backtest_contribution_per_period_defaults_to_500(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "bt.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks([{"symbol": "AAA", "price": 100.0, "currency": "USD"}])
    real_init = SQLiteStore.__init__

    def _init(self, *args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(SQLiteStore, "__init__", _init)
    monkeypatch.setattr(app, "get_store", lambda: SQLiteStore(db_path=db_path))
    st.cache_resource.clear()
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.run()

    assert not at.exception
    field = next(
        item for item in at.number_input if item.label == "Contribution per period"
    )
    assert field.value == 500.0
