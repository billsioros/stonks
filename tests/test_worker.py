"""Tests for the StockAnalysis-backed background worker."""

import json
import time
from unittest.mock import MagicMock

import pytest

from stonks import alerts, sanity, worker
from stonks.store import SQLiteStore
from stonks.worker import fetch_watched_news, job

_REAL_SANITY_LOAD_REPORT = sanity.load_report
_REAL_SANITY_SAVE_REPORT = sanity.save_report


@pytest.fixture(autouse=True)
def _offline_sanity(monkeypatch):
    """The job's cross-checks hit four live sites; tests stub them out."""
    monkeypatch.setattr(sanity, "load_report", lambda store: None)
    monkeypatch.setattr(sanity, "run_sanity_checks", lambda store: [])
    monkeypatch.setattr(sanity, "save_report", lambda store, results, **kwargs: None)


def _stub_store(
    monkeypatch, monitored: list[str] | None = None, held: list[str] | None = None
) -> MagicMock:
    store = MagicMock(spec=SQLiteStore)
    store.get_watchlist_symbols.return_value = []
    store.get_monitored_symbols.return_value = monitored or []
    store.get_position_symbols.return_value = held or []
    store.get_stocks.return_value = ([], 0, 0)
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


def test_job_records_daily_move_alert_from_the_first_price(monkeypatch, tmp_path):
    store = _real_store(monkeypatch, tmp_path)
    store.add_to_watchlist("AAA")
    store.replace_stocks([{"symbol": "AAA", "price": 100.0}])
    store.save_metadata(
        "daily_move_baselines",
        json.dumps({"day": "2026-11-25", "prices": {"AAA": 100.0}}),
    )
    monkeypatch.setattr(alerts, "day_bucket", lambda *a, **k: "2026-11-25")
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    _stub_market(monkeypatch, [{"symbol": "AAA", "price": 107.0}])

    job()

    recorded = store.get_alerts(unread_only=False)
    assert [a["kind"] for a in recorded] == ["daily_move_up"]
    assert recorded[0]["dedupe_key"] == "AAA:daily_move_up:2026-11-25"


def test_job_ignores_a_legacy_etf_on_the_watchlist(monkeypatch, tmp_path) -> None:
    store = _real_store(monkeypatch, tmp_path)
    store.add_to_watchlist("VUAA")
    store.replace_stocks([{"symbol": "VUAA", "price": 100.0, "type": "ETF"}])
    store.save_metadata(
        "daily_move_baselines",
        json.dumps({"day": "2026-11-25", "prices": {"VUAA": 100.0}}),
    )
    monkeypatch.setattr(alerts, "day_bucket", lambda *a, **k: "2026-11-25")
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    _stub_market(monkeypatch, [{"symbol": "VUAA", "price": 107.0, "type": "ETF"}])

    job()

    assert store.get_alerts(unread_only=False) == []


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
        lambda store, results, **kwargs: saved.update(count=len(results)),
    )

    worker._maybe_run_sanity_checks(store)

    assert saved == {"count": 1}


def test_job_leaves_a_future_lease_when_it_is_interrupted(
    monkeypatch, tmp_path
) -> None:
    store = _real_store(monkeypatch, tmp_path)
    now = 1000.0
    monkeypatch.setattr(worker, "_now", lambda: now, raising=False)
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(worker, "fetch_rows", interrupt)

    with pytest.raises(KeyboardInterrupt):
        job()

    assert float(store.get_metadata("next_sync_at")) == now + 15 * 60


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


def test_failed_sync_schedules_a_near_term_retry(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "retry.db")
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    monkeypatch.setattr(
        worker,
        "fetch_rows",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("provider offline")),
    )

    job()

    wait = float(store.get_metadata("next_sync_at")) - time.time()
    assert 60 <= wait <= 90
    assert store.get_metadata("sync_failure_count") == "1"


def test_repeated_failures_keep_extending_the_wait(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "retry.db")
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    monkeypatch.setattr(
        worker,
        "fetch_rows",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("provider offline")),
    )

    job()
    first_wait = float(store.get_metadata("next_sync_at")) - time.time()
    job()
    second_wait = float(store.get_metadata("next_sync_at")) - time.time()

    assert second_wait > first_wait
    assert 120 <= second_wait <= 150


def test_a_successful_sync_returns_to_the_fifteen_minute_cadence(
    monkeypatch, tmp_path
) -> None:
    store = SQLiteStore(db_path=tmp_path / "retry.db")
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    monkeypatch.setattr(
        worker,
        "fetch_rows",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("provider offline")),
    )
    job()
    monkeypatch.setattr(
        worker, "fetch_rows", lambda *a, **k: [{"symbol": "AAPL", "price": 1.0}]
    )

    job()

    wait = float(store.get_metadata("next_sync_at")) - time.time()
    assert 880 <= wait <= 900
    assert store.get_metadata("sync_failure_count") == "0"


def test_worker_loop_waits_for_the_recorded_next_attempt(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "loop.db")
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    scheduled = iter([60.0, 120.0])
    waits: list[float] = []

    class StopLoop(Exception):
        pass

    def fake_job() -> None:
        store.save_metadata("next_sync_at", str(time.time() + next(scheduled)))

    def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 2:
            raise StopLoop

    monkeypatch.setattr(worker, "job", fake_job)
    monkeypatch.setattr(worker.time, "sleep", fake_sleep)

    with pytest.raises(StopLoop):
        worker.run_worker()

    assert len(waits) == 2
    assert 59 <= waits[0] <= 60
    assert 119 <= waits[1] <= 120


def test_a_slow_failed_sync_still_pauses_before_retrying(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "slow.db")
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    monkeypatch.setattr(
        worker,
        "fetch_rows",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("slow provider")),
    )
    monkeypatch.setattr(worker.random, "uniform", lambda low, high: 0.0)
    clock = iter([1000.0, 1000.0, 1090.0])
    monkeypatch.setattr(worker, "_now", lambda: next(clock), raising=False)

    job()

    assert float(store.get_metadata("next_sync_at")) == 1150.0


def test_worker_honors_a_pending_backoff_before_the_first_job(
    monkeypatch, tmp_path
) -> None:
    store = SQLiteStore(db_path=tmp_path / "restart.db")
    now = 1000.0
    store.save_metadata("next_sync_at", str(now + 120))
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    monkeypatch.setattr(worker, "_now", lambda: now, raising=False)
    calls: list[str] = []
    monkeypatch.setattr(worker, "job", lambda: calls.append("job"))

    class StopLoop(Exception):
        pass

    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise StopLoop

    monkeypatch.setattr(worker.time, "sleep", fake_sleep)

    with pytest.raises(StopLoop):
        worker.run_worker()

    assert calls == []
    assert sleeps == [120.0]


def test_retry_ladder_caps_at_the_normal_interval(monkeypatch) -> None:
    monkeypatch.setattr(worker.random, "uniform", lambda low, high: 0.0)

    assert worker.retry_delay_seconds(5) == 15 * 60
    assert worker.retry_delay_seconds(6) == 15 * 60


def test_retry_jitter_stays_under_ten_seconds(monkeypatch) -> None:
    monkeypatch.setattr(worker.random, "uniform", lambda low, high: high)

    assert worker.retry_delay_seconds(1) <= 70


def test_stale_future_schedule_is_clamped_to_the_interval(
    monkeypatch, tmp_path
) -> None:
    store = SQLiteStore(db_path=tmp_path / "clamp.db")
    now = 1000.0
    store.save_metadata("next_sync_at", str(now + 3600))
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    monkeypatch.setattr(worker, "_now", lambda: now, raising=False)

    assert worker._next_sync_delay(default=0.0) == 15 * 60


def test_screener_report_prompt_explains_the_13f_flag() -> None:
    from stonks import report

    prompt = report.screener_report_prompt(
        [{"symbol": "AAA", "hedge_fund_buys": 0}], total_matching=1
    )
    lowered = prompt.lower()
    assert "13f" in lowered
    assert "45 days" in lowered
    assert "do not penalize" in lowered


def test_sanity_checks_record_the_next_sync_attempt(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    now = 1000.0
    store.save_metadata("next_sync_at", str(now + 90))
    monkeypatch.setattr(sanity, "load_report", _REAL_SANITY_LOAD_REPORT)
    monkeypatch.setattr(sanity, "save_report", _REAL_SANITY_SAVE_REPORT)
    monkeypatch.setattr(sanity.time, "time", lambda: now)
    monkeypatch.setattr(
        sanity,
        "run_sanity_checks",
        lambda store: [sanity.CheckResult("A", "b", True, "c")],
    )

    worker._maybe_run_sanity_checks(store)

    report = sanity.load_report(store)
    assert report is not None
    assert report["checked_at"] == now
    assert report["next_check_at"] == now + 90
    assert "Next check in 1m." in sanity.compatibility(report, now=now).detail


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


def test_job_alerts_a_held_etf_but_not_a_watchlist_only_etf(
    monkeypatch, tmp_path
) -> None:
    store = _real_store(monkeypatch, tmp_path)
    store.add_to_watchlist("WET")
    store.add_position("VUAA", 1, 100.0)
    store.replace_stocks(
        [
            {"symbol": "WET", "price": 100.0, "type": "ETF"},
            {"symbol": "VUAA", "price": 100.0, "type": "ETF"},
        ]
    )
    monkeypatch.setattr(alerts, "day_bucket", lambda *a, **k: "2026-11-25")
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    monkeypatch.setattr("stonks.worker.fetch_watched_news", lambda *a, **k: 0)
    monkeypatch.setattr(
        "stonks.worker.fetch_rows",
        lambda discount_rate=None: [
            {"symbol": "WET", "price": 107.0, "type": "ETF"},
            {"symbol": "VUAA", "price": 107.0, "type": "ETF"},
        ],
    )

    job()

    kinds = [alert["kind"] for alert in store.get_alerts(unread_only=False)]
    assert kinds == ["daily_move_up"]
    assert store.get_alerts(unread_only=False)[0]["symbol"] == "VUAA"


def test_job_fetches_news_for_holdings_outside_the_stored_universe(monkeypatch) -> None:
    _stub_store(monkeypatch, monitored=["GHOST"], held=["GHOST"])
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    monkeypatch.setattr("stonks.worker.fetch_rows", lambda discount_rate=None: [])
    seen: list[list[str]] = []
    monkeypatch.setattr(
        "stonks.worker.fetch_watched_news",
        lambda _store, symbols: seen.append(symbols) or 0,
    )

    job()

    assert seen == [["GHOST"]]


def test_job_fetches_news_for_held_etf_but_not_watchlist_only_etf(
    monkeypatch, tmp_path
) -> None:
    store = _real_store(monkeypatch, tmp_path)
    store.add_to_watchlist("AAA")
    store.add_to_watchlist("WET")
    store.add_position("VUAA", 1, 100.0)
    store.replace_stocks(
        [
            {"symbol": "AAA", "price": 100.0, "type": "Stock"},
            {"symbol": "WET", "price": 100.0, "type": "ETF"},
            {"symbol": "VUAA", "price": 100.0, "type": "ETF"},
        ]
    )
    _stub_discount_rate(monkeypatch)
    _stub_largest_buys(monkeypatch)
    monkeypatch.setattr(
        "stonks.worker.fetch_rows",
        lambda discount_rate=None: [
            {"symbol": "AAA", "price": 100.0, "type": "Stock"},
            {"symbol": "WET", "price": 100.0, "type": "ETF"},
            {"symbol": "VUAA", "price": 100.0, "type": "ETF"},
        ],
    )
    seen: list[list[str]] = []
    monkeypatch.setattr(
        "stonks.worker.fetch_watched_news",
        lambda _store, symbols: seen.append(symbols) or 0,
    )

    job()

    assert seen == [["AAA", "VUAA"]]
