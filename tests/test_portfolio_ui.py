from typing import Any

import streamlit as st
from streamlit.testing.v1 import AppTest

from stonks import app, backtest_view, correlation, detail
from stonks.backtest import simulate
from stonks.backtest_view import _RESULT_KEY
from stonks.store import SQLiteStore


def _stock(
    symbol: str, price: float = 100.0, currency: str = "USD", type_: str = "Stock"
):
    return {
        "symbol": symbol,
        "description": f"{symbol} Inc",
        "price": price,
        "currency": currency,
        "type": type_,
    }


def _app_with_db(db_path, monkeypatch):
    real_init = SQLiteStore.__init__

    def _init(self, *args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(SQLiteStore, "__init__", _init)
    monkeypatch.setattr(app, "get_store", lambda: SQLiteStore(db_path=db_path))
    st.cache_resource.clear()
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.session_state["active_filters"] = {}
    at.run()
    return at


def _complete_backtest_result(symbols: list[str]) -> dict[str, Any]:
    """A renderable result, since the Backtest tab renders after the handoff."""
    prices = {
        symbol: {
            "2024-01": 100.0,
            "2024-12": 110.0,
            "2025-01": 110.0,
            "2025-12": 130.0,
        }
        for symbol in symbols
    }
    result = simulate(prices, {symbol: 1.0 for symbol in symbols}, initial=1000.0)
    result.update(
        {
            "symbols": symbols,
            "weights": {symbol: 100.0 / len(symbols) for symbol in symbols},
            "rebalance": "none",
            "allocation_mode": "percent",
        }
    )
    return result


def _offline(url: str) -> dict[str, Any]:
    raise OSError("offline")


def test_portfolio_table_aggregates_lots_into_one_row(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "pf.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks([_stock("AAA", 110.0)])
    store.add_position("AAA", 2, 100.0, "USD")
    store.add_position("AAA", 3, 120.0, "USD")
    store.cache_set(
        "hist:AAA:1Y",
        [
            {"date": "2026-11-24", "close": 100.0},
            {"date": "2026-11-25", "close": 110.0},
        ],
        ttl_seconds=60,
    )

    at = _app_with_db(db_path, monkeypatch)

    assert not at.exception
    table = next(item for item in at.dataframe if "Position" in item.value.columns)
    row = table.value.iloc[0]
    assert row["Instrument"].startswith("AAA")
    assert row["Position"] == 5
    assert row["Avg Price"] == "112.00 USD"
    assert row["Cost Basis"] == "560.00 USD"
    assert row["Market Value"] == "550.00 USD"
    metrics = [item.value for item in at.metric]
    assert any("$550.00" in str(value) for value in metrics)


def test_portfolio_correlation_card_shows_a_number(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "pf.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks([_stock("AAA", 110.0), _stock("BBB", 110.0)])
    store.add_position("AAA", 1, 100.0, "USD")
    store.add_position("BBB", 1, 100.0, "USD")
    monkeypatch.setattr(
        correlation, "portfolio_correlation_factor", lambda *a, **k: 0.85
    )

    at = _app_with_db(db_path, monkeypatch)

    assert not at.exception
    card = next(item for item in at.metric if item.label == "Portfolio correlation")
    assert card.value == "+0.85"


def test_portfolio_adds_an_etf_lot(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "pf.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks([_stock("VUAA", 110.0, "EUR", "ETF")])

    at = _app_with_db(db_path, monkeypatch)
    panel = next(item for item in at.expander if "Add lot" in item.label)
    panel.text_input[0].set_value("VUAA")
    panel.number_input[0].set_value(79)
    panel.number_input[1].set_value(101.16)
    panel.selectbox[0].set_value("EUR")
    next(button for button in panel.button if button.label == "Add lot").click().run()

    assert not at.exception
    assert [(row["symbol"], row["currency"]) for row in store.get_positions()] == [
        ("VUAA", "EUR")
    ]


def test_portfolio_deletes_one_lot(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "pf.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks([_stock("AAA")])
    store.add_position("AAA", 1, 100.0)
    store.add_position("AAA", 2, 100.0)

    at = _app_with_db(db_path, monkeypatch)
    first_id = store.get_positions()[0]["id"]
    panel = next(item for item in at.expander if "Lots" in item.label)
    next(
        button for button in panel.button if button.key == f"pf_delete_{first_id}"
    ).click().run()

    assert not at.exception
    assert [row["quantity"] for row in store.get_positions()] == [2.0]


def test_portfolio_backtest_button_runs_immediately(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "pf.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks([_stock("AAA", 110.0)])
    store.add_position("AAA", 1, 100.0, "USD")
    captured = {}
    monkeypatch.setattr(
        backtest_view,
        "run_configured_backtest",
        lambda _store, settings: (
            captured.update(settings) or _complete_backtest_result(settings["symbols"])
        ),
    )

    at = _app_with_db(db_path, monkeypatch)
    next(button for button in at.button if button.key == "pf_backtest").click().run()

    assert not at.exception
    assert captured["symbols"] == ["AAA"]
    assert at.session_state[_RESULT_KEY]["symbols"] == ["AAA"]
    assert at.session_state["page"] == "backtest"


def test_portfolio_warns_about_stale_fx_and_excluded_holding(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "pf.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks(
        [_stock("AAA", price=None), _stock("VUAA", 110.0, "EUR", "ETF")]
    )
    store.add_position("AAA", 1, 100.0, "USD")
    store.add_position("VUAA", 1, 100.0, "EUR")
    store.cache_set("fx:EURUSD", 1.08, ttl_seconds=-1)
    for symbol in ("AAA", "VUAA"):
        store.cache_set(
            f"hist:{symbol}:1Y",
            [{"date": "2026-11-24", "close": 100.0}],
            ttl_seconds=60,
        )
    monkeypatch.setattr("stonks.portfolio.fetch_json", _offline)

    at = _app_with_db(db_path, monkeypatch)

    assert not at.exception
    warnings = [str(item.value) for item in at.warning]
    assert any("Stale EUR→USD rate" in text for text in warnings)
    assert any("1 holding excluded from USD totals: AAA" in text for text in warnings)


def test_portfolio_blanks_daily_fields_when_history_is_missing(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "pf.db"
    store = SQLiteStore(db_path=db_path)
    store.replace_stocks([_stock("AAA", 110.0)])
    store.add_position("AAA", 2, 100.0, "USD")
    monkeypatch.setattr(detail, "fetch_json", _offline)

    at = _app_with_db(db_path, monkeypatch)

    assert not at.exception
    table = next(item for item in at.dataframe if "Position" in item.value.columns)
    row = table.value.iloc[0]
    assert row["Change %"] == "—"
    assert row["Daily P&L"] == "—"
    assert row["Market Value"] == "220.00 USD"
    assert row["USD Value"] == "220.00 USD"
    assert any("$220.00" in str(item.value) for item in at.metric)
