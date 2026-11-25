import streamlit as st
from streamlit.testing.v1 import AppTest

from stonks import app
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
    monkeypatch.setattr(app, "portfolio_correlation_factor", lambda *a, **k: 0.85)

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
        app,
        "run_configured_backtest",
        lambda _store, settings: (
            captured.update(settings) or {"yearly": {}, "symbols": settings["symbols"]}
        ),
    )

    at = _app_with_db(db_path, monkeypatch)
    next(button for button in at.button if button.key == "pf_backtest").click().run()

    assert not at.exception
    assert captured["symbols"] == ["AAA"]
    assert at.session_state[_RESULT_KEY]["symbols"] == ["AAA"]
    assert at.session_state["page"] == "backtest"
