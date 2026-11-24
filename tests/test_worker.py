"""Tests for the StockAnalysis-backed background worker."""

from unittest.mock import MagicMock

import pytest

from stonks import sanity, worker
from stonks.store import SQLiteStore
from stonks.worker import fetch_watched_news, job


@pytest.fixture(autouse=True)
def _offline_sanity(monkeypatch):
    """The job's cross-checks hit four live sites; tests stub them out."""
    monkeypatch.setattr(sanity, "load_report", lambda store: None)
    monkeypatch.setattr(sanity, "run_sanity_checks", lambda store: [])
    monkeypatch.setattr(sanity, "save_report", lambda store, results: None)


def _stub_store(monkeypatch) -> MagicMock:
    store = MagicMock(spec=SQLiteStore)
    store.get_watchlist_symbols.return_value = []
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
    # Sync health now rides along with the universe size.
    store.save_metadata.assert_any_call("universe_size", 2)


def test_job_skips_writes_when_fetch_returns_no_rows(monkeypatch):
    store = _stub_store(monkeypatch)
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    monkeypatch.setattr("stonks.worker.fetch_rows", lambda discount_rate=None: [])

    job()

    store.replace_stocks.assert_not_called()
    store.save_metadata.assert_any_call("last_sync_status", "failed")
    store.save_metadata.assert_any_call(
        "last_sync_error", "No screener data returned from provider"
    )


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
    store.save_metadata.assert_any_call("last_sync_status", "failed")
    errors = [
        call.args[1]
        for call in store.save_metadata.call_args_list
        if call.args[0] == "last_sync_error"
    ]
    assert any(
        "StockAnalysis" in error and "stockanalysis unavailable" in error
        for error in errors
    )


def _real_store(monkeypatch, tmp_path) -> SQLiteStore:
    store = SQLiteStore(db_path=tmp_path / "worker.db")
    monkeypatch.setattr("stonks.worker.SQLiteStore", lambda: store)
    return store


def _stub_market(monkeypatch, rows) -> None:
    monkeypatch.setattr("stonks.worker.fetch_rows", lambda discount_rate=None: rows)
    monkeypatch.setattr("stonks.worker.fetch_watched_news", lambda *a, **k: 0)


def test_job_records_alert_when_watched_symbol_drops_off_its_high(
    monkeypatch, tmp_path
):
    store = _real_store(monkeypatch, tmp_path)
    store.add_to_watchlist("AAA")
    store.replace_stocks([{"symbol": "AAA", "price": 161.0, "week_52_high": 200.0}])
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    _stub_market(
        monkeypatch, [{"symbol": "AAA", "price": 159.0, "week_52_high": 200.0}]
    )

    job()

    assert [a["kind"] for a in store.get_alerts()] == ["off_high"]


def test_job_ignores_unwatched_symbols(monkeypatch, tmp_path):
    store = _real_store(monkeypatch, tmp_path)
    store.replace_stocks([{"symbol": "AAA", "price": 161.0, "week_52_high": 200.0}])
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    _stub_market(
        monkeypatch, [{"symbol": "AAA", "price": 159.0, "week_52_high": 200.0}]
    )

    job()

    assert store.get_alerts(unread_only=False) == []


def test_job_does_not_repeat_an_alert_within_the_week(monkeypatch, tmp_path):
    store = _real_store(monkeypatch, tmp_path)
    store.add_to_watchlist("AAA")
    store.replace_stocks([{"symbol": "AAA", "price": 161.0, "week_52_high": 200.0}])
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    _stub_market(
        monkeypatch, [{"symbol": "AAA", "price": 159.0, "week_52_high": 200.0}]
    )

    job()
    # The price bounced back and crossed the line a second time.
    store.replace_stocks([{"symbol": "AAA", "price": 161.0, "week_52_high": 200.0}])
    job()

    assert len(store.get_alerts(unread_only=False)) == 1


def test_job_with_empty_watchlist_writes_no_alerts(monkeypatch, tmp_path):
    store = _real_store(monkeypatch, tmp_path)
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    _stub_market(
        monkeypatch, [{"symbol": "AAA", "price": 159.0, "week_52_high": 200.0}]
    )

    job()

    assert store.get_alerts(unread_only=False) == []
    assert store.get_metadata("universe_size") == "1"


def _overview(items):
    return {"news": {"data": items}}


def test_fetch_watched_news_only_reports_unseen_links(monkeypatch, tmp_path):
    store = _real_store(monkeypatch, tmp_path)
    items = [
        {
            "url": "https://x/a",
            "title": "A",
            "source": "WSJ",
            "ago": "1 hour ago",
            "text": "",
        },
        {
            "url": "https://x/b",
            "title": "B",
            "source": "BI",
            "ago": "2 hours ago",
            "text": "",
        },
    ]
    monkeypatch.setattr(
        "stonks.worker.load_page", lambda *a, **k: (_overview(items), 1.0)
    )

    assert fetch_watched_news(store, ["AAA"]) == 2
    assert fetch_watched_news(store, ["AAA"]) == 0

    news = {a["dedupe_key"]: a for a in store.get_alerts() if a["kind"] == "news"}
    assert set(news) == {"AAA:news:https://x/a", "AAA:news:https://x/b"}
    assert news["AAA:news:https://x/a"]["severity"] == "info"
    assert news["AAA:news:https://x/a"]["detail"] == "WSJ · 1 hour ago"


def test_fetch_watched_news_caps_per_sync(monkeypatch, tmp_path):
    store = _real_store(monkeypatch, tmp_path)
    items = [
        {
            "url": f"https://x/{i}",
            "title": f"T{i}",
            "source": "WSJ",
            "ago": "1 hour ago",
        }
        for i in range(5)
    ]
    monkeypatch.setattr(
        "stonks.worker.load_page", lambda *a, **k: (_overview(items), 1.0)
    )

    assert fetch_watched_news(store, ["AAA"]) == 3


def test_fetch_watched_news_skips_unreachable_symbols(monkeypatch, tmp_path):
    store = _real_store(monkeypatch, tmp_path)
    monkeypatch.setattr("stonks.worker.load_page", lambda *a, **k: (None, None))

    assert fetch_watched_news(store, ["ZZZZ"]) == 0
    assert store.get_alerts(unread_only=False) == []


def test_sanity_checks_run_when_the_report_is_stale(monkeypatch) -> None:
    store = MagicMock(spec=SQLiteStore)
    monkeypatch.setattr(sanity, "load_report", lambda store: None)
    monkeypatch.setattr(
        sanity,
        "run_sanity_checks",
        lambda store: [sanity.CheckResult("A", "b", True, "c")],
    )
    saved = {}
    monkeypatch.setattr(
        sanity,
        "save_report",
        lambda store, results: saved.update(count=len(results)),
    )

    worker._maybe_run_sanity_checks(store)

    assert saved == {"count": 1}


def test_job_persists_failure_metadata_on_exception(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)

    def fail_fetch(*args, **kwargs):
        raise ConnectionError("StockAnalysis timeout")

    monkeypatch.setattr(worker, "fetch_rows", fail_fetch)

    job()
    assert store.get_metadata("last_sync_status") == "failed"
    assert "StockAnalysis timeout" in store.get_metadata("last_sync_error")


def test_job_survives_a_store_that_cannot_be_opened(monkeypatch) -> None:
    def boom():
        raise OSError("disk unavailable")

    monkeypatch.setattr(worker, "SQLiteStore", boom)

    # The worker loop must not die because one sync could not open the store.
    job()


def test_job_persists_success_metadata(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    _stub_discount_rate(monkeypatch)
    monkeypatch.setattr(
        worker, "fetch_rows", lambda *a, **k: [{"symbol": "AAPL", "market_cap": 100.0}]
    )
    monkeypatch.setattr(worker, "fetch_largest_buys", lambda: set())

    job()
    assert store.get_metadata("last_sync_status") == "success"
    assert store.get_metadata("last_successful_sync_at") is not None


def test_screener_report_prompt_explains_the_13f_flag() -> None:
    from stonks import report

    prompt = report.screener_report_prompt(
        [{"symbol": "AAA", "hedge_fund_buys": 0}], total_matching=1
    )
    lowered = prompt.lower()
    assert "13f" in lowered
    assert "45 days" in lowered
    assert "do not penalize" in lowered


def test_sanity_checks_skip_a_fresh_report(monkeypatch) -> None:
    store = MagicMock(spec=SQLiteStore)
    monkeypatch.setattr(sanity, "load_report", lambda store: {"checked_at": 1.0})
    monkeypatch.setattr(sanity, "report_is_fresh", lambda report: True)

    def fail(store):
        raise AssertionError("checks should not run while the report is fresh")

    monkeypatch.setattr(sanity, "run_sanity_checks", fail)

    worker._maybe_run_sanity_checks(store)


def test_job_persists_buy_opportunity_alerts(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    monkeypatch.setattr(
        worker,
        "fetch_rows",
        lambda *a, **k: [
            {
                "symbol": "BOTH",
                "description": "Cheap and below models",
                "price": 94.0,
                "week_52_low": 90.0,
                "dcf_fair_value": 120.0,
                "lynch_fair_value": 110.0,
            },
            {
                "symbol": "NEAR",
                "description": "Near low only",
                "price": 94.0,
                "week_52_low": 90.0,
                "dcf_fair_value": None,
                "lynch_fair_value": None,
            },
        ],
    )

    job()
    job()

    alerts = store.get_alerts(unread_only=False)
    buy_alerts = [a for a in alerts if a["kind"] == "buy_opportunity"]
    assert len(buy_alerts) == 1
    assert buy_alerts[0]["symbol"] == "BOTH"
