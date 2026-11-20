"""Tests for the StockAnalysis-backed background worker."""

from unittest.mock import MagicMock, call

from stonks.store import SQLiteStore
from stonks.worker import job


def _stub_store(monkeypatch) -> MagicMock:
    store = MagicMock(spec=SQLiteStore)
    monkeypatch.setattr("stonks.worker.SQLiteStore", lambda: store)
    return store


def test_job_persists_every_fetched_row(monkeypatch):
    store = _stub_store(monkeypatch)
    rows = [
        {"symbol": "AAA", "price": 10.0},
        {"symbol": "BBB", "price": 20.0},
    ]
    monkeypatch.setattr("stonks.worker.fetch_rows", lambda: rows)

    job()

    assert store.save_stock.call_args_list == [
        call("AAA", rows[0]),
        call("BBB", rows[1]),
    ]
    assert [c.args for c in store.update_sync_status.call_args_list] == [
        ("AAA", "fundamentals", "success"),
        ("BBB", "fundamentals", "success"),
    ]
    store.save_metadata.assert_called_once_with("universe_size", 2)


def test_job_skips_writes_when_fetch_returns_no_rows(monkeypatch):
    store = _stub_store(monkeypatch)
    monkeypatch.setattr("stonks.worker.fetch_rows", list)

    job()

    store.save_stock.assert_not_called()
    store.update_sync_status.assert_not_called()
    store.save_metadata.assert_not_called()


def test_job_leaves_store_untouched_when_fetch_fails(monkeypatch):
    store = _stub_store(monkeypatch)

    def boom():
        raise OSError("stockanalysis unavailable")

    monkeypatch.setattr("stonks.worker.fetch_rows", boom)

    job()

    store.save_stock.assert_not_called()
    store.update_sync_status.assert_not_called()
    store.save_metadata.assert_not_called()
