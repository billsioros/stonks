"""Tests for the Yahoo-backed background worker."""

from unittest.mock import MagicMock

from stonks.store import SQLiteStore
from stonks.worker import job


def _stub_store(monkeypatch) -> MagicMock:
    store = MagicMock(spec=SQLiteStore)
    store.get_synced_symbols.return_value = []
    store.get_stale_symbols.return_value = []
    monkeypatch.setattr("stonks.worker.SQLiteStore", lambda: store)
    return store


def test_job_runs_without_credentials(monkeypatch):
    store = _stub_store(monkeypatch)
    monkeypatch.setattr(
        "stonks.worker.preset_candidate_rows",
        lambda: [{"symbol": "AAA", "market_cap": 1000.0}],
    )
    monkeypatch.setattr("stonks.worker.enrich_rows", lambda rows, columns: rows)
    monkeypatch.setattr("stonks.worker.required_preset_columns", lambda: set())

    job()

    assert store.save_stock.call_count == 1


def test_job_saves_quote_rows_and_marks_enriched(monkeypatch):
    store = _stub_store(monkeypatch)
    monkeypatch.setattr(
        "stonks.worker.preset_candidate_rows",
        lambda: [{"symbol": "AAA", "price": 10.0}, {"symbol": "BBB", "price": 20.0}],
    )
    monkeypatch.setattr(
        "stonks.worker.enrich_rows",
        lambda rows, columns: [{**row, "roic_5y_avg_pct": 12.0} for row in rows],
    )
    monkeypatch.setattr(
        "stonks.worker.required_preset_columns", lambda: {"roic_5y_avg_pct"}
    )

    job()

    assert store.save_stock.call_count == 2
    assert all(
        call.args[2] == "success" for call in store.update_sync_status.call_args_list
    )


def test_enrich_preserves_cached_row_on_error(monkeypatch):
    statuses = []
    store = _stub_store(monkeypatch)
    store.update_sync_status.side_effect = lambda *args: statuses.append(args)
    monkeypatch.setattr(
        "stonks.worker.preset_candidate_rows",
        lambda: [{"symbol": "AAA", "price": 1.0}],
    )

    def boom(rows, columns):
        raise RuntimeError("Yahoo 429")

    monkeypatch.setattr("stonks.worker.enrich_rows", boom)
    monkeypatch.setattr("stonks.worker.required_preset_columns", lambda: set())

    job()

    assert store.save_stock.call_count == 1
    assert any(call[0] == "AAA" and call[2] == "failed" for call in statuses)


def test_job_marks_symbol_failed_when_enrichment_returns_no_values(monkeypatch):
    statuses = []
    store = _stub_store(monkeypatch)
    store.update_sync_status.side_effect = lambda *args: statuses.append(args)
    monkeypatch.setattr(
        "stonks.worker.preset_candidate_rows", lambda: [{"symbol": "AAA"}]
    )
    monkeypatch.setattr(
        "stonks.worker.enrich_rows",
        lambda rows, columns: [
            {"symbol": "AAA", "roe_pct": None, "gross_margin_pct": None}
        ],
    )
    monkeypatch.setattr(
        "stonks.worker.required_preset_columns", lambda: {"roe_pct", "gross_margin_pct"}
    )

    job()

    assert any(call[0] == "AAA" and call[2] == "failed" for call in statuses)


def test_job_skips_fresh_symbols(monkeypatch):
    store = _stub_store(monkeypatch)
    store.get_synced_symbols.return_value = ["AAA"]
    called = []
    monkeypatch.setattr(
        "stonks.worker.preset_candidate_rows", lambda: [{"symbol": "AAA"}]
    )
    monkeypatch.setattr(
        "stonks.worker.enrich_rows",
        lambda rows, columns: called.extend(rows) or rows,
    )
    monkeypatch.setattr("stonks.worker.required_preset_columns", lambda: set())

    job()

    assert called == []
    assert store.save_stock.call_count == 1
