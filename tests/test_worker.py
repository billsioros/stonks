"""Tests for the Yahoo-backed background worker."""

from unittest.mock import MagicMock

from stonks.store import SQLiteStore
from stonks.worker import job


def _stub_store(monkeypatch) -> MagicMock:
    store = MagicMock(spec=SQLiteStore)
    store.get_synced_symbols.return_value = []
    store.get_stale_symbols.return_value = []
    store.get_failed_attempts.return_value = {}
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
    store.update_sync_status.side_effect = lambda *args, **kwargs: statuses.append(args)
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
    store.update_sync_status.side_effect = lambda *args, **kwargs: statuses.append(args)
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


def test_job_retries_screener_with_backoff(monkeypatch):
    store = _stub_store(monkeypatch)
    calls = []
    sleeps = []
    monkeypatch.setattr(
        "stonks.worker.time.sleep", lambda seconds: sleeps.append(seconds)
    )

    def flaky_screen():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("429")
        return [{"symbol": "AAA"}]

    monkeypatch.setattr("stonks.worker.preset_candidate_rows", flaky_screen)
    monkeypatch.setattr("stonks.worker.enrich_rows", lambda rows, columns: rows)
    monkeypatch.setattr("stonks.worker.required_preset_columns", lambda: set())

    job()

    assert len(calls) == 3
    assert sleeps == [5.0, 10.0]
    assert store.save_stock.call_count == 1


def test_job_gives_up_after_screener_attempts(monkeypatch):
    store = _stub_store(monkeypatch)
    calls = []
    monkeypatch.setattr("stonks.worker.time.sleep", lambda seconds: None)

    def always_fail():
        calls.append(1)
        raise RuntimeError("429")

    monkeypatch.setattr("stonks.worker.preset_candidate_rows", always_fail)

    job()

    assert len(calls) == 4
    assert store.save_stock.call_count == 0


def test_job_batches_enrichment_and_checkpoints(monkeypatch):
    store = _stub_store(monkeypatch)
    sleeps = []
    batch_sizes = []
    status_calls = []
    monkeypatch.setattr(
        "stonks.worker.time.sleep", lambda seconds: sleeps.append(seconds)
    )
    monkeypatch.setattr("stonks.worker.WORKER_BATCH_SIZE", 2)
    monkeypatch.setattr("stonks.worker.WORKER_BATCH_COOLDOWN", 7.0)
    monkeypatch.setattr(
        "stonks.worker.preset_candidate_rows",
        lambda: [{"symbol": symbol} for symbol in ("A", "B", "C", "D", "E")],
    )

    def fake_enrich(rows, columns):
        batch_sizes.append(len(rows))
        return [{**row, "roic_5y_avg_pct": 12.0} for row in rows]

    monkeypatch.setattr("stonks.worker.enrich_rows", fake_enrich)
    monkeypatch.setattr(
        "stonks.worker.required_preset_columns", lambda: {"roic_5y_avg_pct"}
    )
    store.update_sync_status.side_effect = lambda *args, **kwargs: status_calls.append(
        (args, kwargs)
    )

    job()

    assert batch_sizes == [2, 2, 1]
    assert sleeps == [7.0, 7.0]
    assert store.save_stock.call_count == 5
    assert all(args[2] == "success" for args, _ in status_calls)


def test_job_respects_retry_backoff_and_attempt_cap(monkeypatch):
    store = _stub_store(monkeypatch)
    now = 1_000_000.0
    monkeypatch.setattr("stonks.worker.time.time", lambda: now)
    monkeypatch.setattr("stonks.worker.WORKER_RETRY_BASE_DELAY", 5.0)
    monkeypatch.setattr("stonks.worker.WORKER_MAX_ATTEMPTS", 3)
    # "READY" failed once long ago (due); "WAIT" failed once just now (not due);
    # "DONE" is at the attempt cap (never retried).
    store.get_failed_attempts.return_value = {
        "READY": (1, now - 100),
        "WAIT": (1, now - 1),
        "DONE": (3, now - 1000),
    }
    enriched = []

    monkeypatch.setattr(
        "stonks.worker.preset_candidate_rows",
        lambda: [{"symbol": symbol} for symbol in ("READY", "WAIT", "DONE")],
    )
    monkeypatch.setattr(
        "stonks.worker.enrich_rows",
        lambda rows, columns: enriched.extend(rows) or rows,
    )
    monkeypatch.setattr("stonks.worker.required_preset_columns", lambda: set())

    job()

    assert {row["symbol"] for row in enriched} == {"READY"}
    assert store.save_stock.call_count == 3


def test_transport_error_does_not_consume_attempt(monkeypatch):
    store = _stub_store(monkeypatch)
    statuses = []
    now = 1_000_000.0
    monkeypatch.setattr("stonks.worker.time.time", lambda: now)
    monkeypatch.setattr("stonks.worker.WORKER_MAX_ATTEMPTS", 3)
    store.get_failed_attempts.return_value = {"AAA": (2, now - 100)}
    store.update_sync_status.side_effect = lambda *args, **kwargs: statuses.append(
        (args, kwargs)
    )
    monkeypatch.setattr(
        "stonks.worker.preset_candidate_rows", lambda: [{"symbol": "AAA"}]
    )

    def boom(rows, columns):
        raise RuntimeError("Yahoo 429")

    monkeypatch.setattr("stonks.worker.enrich_rows", boom)
    monkeypatch.setattr("stonks.worker.required_preset_columns", lambda: {"roe_pct"})

    job()

    failed = [entry for entry in statuses if entry[0][2] == "failed"]
    assert len(failed) == 1
    assert failed[0][1]["attempts"] == 2  # unchanged, still retryable
    assert "transport" in failed[0][0][3]


def test_job_increments_attempts_on_failure(monkeypatch):
    store = _stub_store(monkeypatch)
    statuses = []
    now = 1_000_000.0
    monkeypatch.setattr("stonks.worker.time.time", lambda: now)
    monkeypatch.setattr("stonks.worker.WORKER_RETRY_BASE_DELAY", 5.0)
    store.get_failed_attempts.return_value = {"AAA": (2, now - 100)}
    store.update_sync_status.side_effect = lambda *args, **kwargs: statuses.append(
        (args, kwargs)
    )
    monkeypatch.setattr(
        "stonks.worker.preset_candidate_rows", lambda: [{"symbol": "AAA"}]
    )
    monkeypatch.setattr(
        "stonks.worker.enrich_rows",
        lambda rows, columns: [{"symbol": "AAA", "roe_pct": None}],
    )
    monkeypatch.setattr("stonks.worker.required_preset_columns", lambda: {"roe_pct"})

    job()

    failed = [entry for entry in statuses if entry[0][2] == "failed"]
    assert len(failed) == 1
    assert failed[0][1]["attempts"] == 3
    assert failed[0][1]["backoff_seconds"] == 40.0
