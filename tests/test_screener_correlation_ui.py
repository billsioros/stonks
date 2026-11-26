from streamlit.testing.v1 import AppTest

from stonks import app, correlation
from stonks.store import SQLiteStore


def test_screener_flags_a_highly_correlated_candidate(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "screen.db"
    seeded = SQLiteStore(db_path=db_path)
    seeded.replace_stocks(
        [
            {"symbol": "AAA", "description": "Held", "price": 100.0},
            {"symbol": "BBB", "description": "Candidate", "price": 20.0},
            {"symbol": "CCC", "description": "Uncorrelated", "price": 30.0},
        ]
    )
    seeded.add_position("AAA", 1, 100.0, "USD")
    real_init = SQLiteStore.__init__

    def _init(self, *args, **kwargs):
        kwargs.setdefault("db_path", db_path)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(SQLiteStore, "__init__", _init)
    monkeypatch.setattr(app, "get_store", lambda: SQLiteStore(db_path=db_path))

    def fake_correlation(_store, symbol, *_args, **_kwargs):
        return 0.85 if symbol == "BBB" else 0.10

    monkeypatch.setattr(app, "portfolio_correlation", fake_correlation)
    # AppTest executes app.py in its own module namespace, so patch the source
    # module too: that copy imports portfolio_correlation when it runs.
    monkeypatch.setattr(correlation, "portfolio_correlation", fake_correlation)
    import streamlit as st

    st.cache_resource.clear()
    at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
    at.session_state["active_filters"] = {}
    # The default screen opens on Quality; correlation ships in Overview.
    at.session_state["view_preset"] = "Overview"
    at.run()

    assert not at.exception
    table = next(
        item for item in at.dataframe if "Portfolio Correlation" in item.value.columns
    )
    values = dict(zip(table.value["Symbol"], table.value["Portfolio Correlation"]))
    assert "⚠️ +0.85" in values["BBB"]
    assert values["CCC"] == "+0.10"


def test_correlation_formatter_flags_high_values() -> None:
    assert app._fmt_correlation(0.85) == "⚠️ +0.85"
    assert app._fmt_correlation(0.10) == "+0.10"
    assert app._fmt_correlation(None) == "—"
