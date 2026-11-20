"""Tests for the StockAnalysis-backed background worker."""

from unittest.mock import MagicMock

from stonks.store import SQLiteStore
from stonks.worker import job


def _stub_store(monkeypatch) -> MagicMock:
    store = MagicMock(spec=SQLiteStore)
    monkeypatch.setattr("stonks.worker.SQLiteStore", lambda: store)
    return store


def _stub_discount_rate(monkeypatch, rate: float = 0.11) -> None:
    """Keep the job offline: the real lookup reads the Treasury feed."""
    monkeypatch.setattr("stonks.worker.current_discount_rate", lambda: rate)


def _stub_largest_buys(monkeypatch, buys=None) -> None:
    """Keep the job offline: the real lookup scrapes HedgeFollow."""
    monkeypatch.setattr("stonks.worker.fetch_largest_buys", lambda: buys)


def test_job_persists_every_fetched_row(monkeypatch):
    store = _stub_store(monkeypatch)
    _stub_discount_rate(monkeypatch, 0.12)
    _stub_largest_buys(monkeypatch, {"AAA": 1_000_000.0})
    rows = [
        {"symbol": "AAA", "price": 10.0},
        {"symbol": "BBB", "price": 20.0},
    ]
    calls = []

    def fake_fetch_rows(discount_rate=None):
        calls.append(discount_rate)
        return rows

    monkeypatch.setattr("stonks.worker.fetch_rows", fake_fetch_rows)

    job()

    assert calls == [0.12]
    assert [row["hedge_fund_buys"] for row in rows] == [1, 0]
    store.replace_stocks.assert_called_once_with(rows)
    store.save_metadata.assert_called_once_with("universe_size", 2)


def test_job_skips_writes_when_fetch_returns_no_rows(monkeypatch):
    store = _stub_store(monkeypatch)
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    monkeypatch.setattr("stonks.worker.fetch_rows", lambda discount_rate=None: [])

    job()

    store.replace_stocks.assert_not_called()
    store.save_metadata.assert_not_called()


def test_job_persists_rows_when_hedgefollow_is_unavailable(monkeypatch):
    store = _stub_store(monkeypatch)
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch, None)
    rows = [{"symbol": "AAA", "price": 10.0}]
    monkeypatch.setattr("stonks.worker.fetch_rows", lambda discount_rate=None: rows)

    job()

    # Unknown, not "not in the list": the flag stays out of the row.
    assert "hedge_fund_buys" not in rows[0]
    store.replace_stocks.assert_called_once_with(rows)


def test_job_leaves_store_untouched_when_fetch_fails(monkeypatch):
    store = _stub_store(monkeypatch)
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)

    def boom(discount_rate=None):
        raise OSError("stockanalysis unavailable")

    monkeypatch.setattr("stonks.worker.fetch_rows", boom)

    job()

    store.replace_stocks.assert_not_called()
    store.save_metadata.assert_not_called()
