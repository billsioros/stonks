"""Tests for the reference-site cross-checks."""

from __future__ import annotations

import json
import time
from typing import Any

from stonks import sanity
from stonks.sanity import CheckResult
from stonks.stockanalysis import INITIAL_URL
from stonks.store import SQLiteStore
from stonks.valuation import lynch_fair_value, upside_pct


def _month_series(
    start_year: int, count: int, base: float, step: float
) -> dict[str, float]:
    months: dict[str, float] = {}
    year, month = start_year, 1
    for index in range(count):
        months[f"{year}-{month:02d}"] = base + step * index
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def test_stockanalysis_sanity_check_asserts_under_100k_rows(
    monkeypatch, tmp_path
) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    monkeypatch.setattr(sanity, "default_screen", lambda: {"filters": {}})
    rows = [{"symbol": f"S{i}", "market_cap": 1.0} for i in range(10)]
    monkeypatch.setattr(sanity, "fetch_rows", lambda *a, **k: rows)
    # The check needs stored rows to compare the live screen against.
    store.replace_stocks(rows)

    result = sanity.check_stockanalysis(store)
    assert result.ok is True


def test_stockanalysis_sanity_check_rejects_a_truncated_universe(
    monkeypatch, tmp_path
) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    monkeypatch.setattr(sanity, "default_screen", lambda: {"filters": {}})
    rows = [{"symbol": f"S{i}", "market_cap": 1.0} for i in range(10)]
    monkeypatch.setattr(sanity, "fetch_rows", lambda *a, **k: rows)
    store.replace_stocks(rows)
    monkeypatch.setattr(sanity, "SCREEN_MAX_ROWS", 5)

    result = sanity.check_stockanalysis(store)
    assert result.ok is False
    assert "truncated" in result.detail.lower()


def _seed_portfolio(store: SQLiteStore) -> None:
    # December 2016 through December 2024, the window the check compares.
    store.cache_set("hist:SPY:10Y:Monthly", _month_series(2016, 97, 200.0, 3.0), 3600)
    store.cache_set("hist:BND:10Y:Monthly", _month_series(2016, 97, 80.0, 0.1), 3600)


def test_stockanalysis_check_compares_the_screen(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        sanity, "default_screen", lambda: {"filters": {"market_cap": {"min": 0}}}
    )
    symbols = ["AAA", "BBB", "CCC"]
    universe = {
        "data": {
            "columns": ["s", "n", "industry"],
            "rows": [[symbol, f"{symbol} Inc", "Tech"] for symbol in symbols],
        }
    }
    metrics = {
        "data": {
            "data": {symbol: {"marketCap": 100.0, "price": 10.0} for symbol in symbols}
        }
    }

    def fetch(url: str):
        return universe if url == INITIAL_URL else metrics

    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.replace_stocks(
        [{"symbol": symbol, "market_cap": 100.0} for symbol in symbols]
    )
    result = sanity.check_stockanalysis(store, fetch=fetch)
    assert result.ok is True
    assert "3 symbols now vs 3 stored" in result.detail

    store.replace_stocks([{"symbol": f"OLD{i}", "market_cap": 1.0} for i in range(10)])
    diverged = sanity.check_stockanalysis(store, fetch=fetch)
    assert diverged.ok is False
    assert "3 added" in diverged.detail


def test_stockanalysis_check_fails_on_an_empty_payload(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")

    def fetch(url: str):
        if url == INITIAL_URL:
            return {"data": {"columns": [], "rows": []}}
        return {"data": {"data": {}}}

    result = sanity.check_stockanalysis(store, fetch=fetch)
    assert result.ok is False
    assert "no rows" in result.detail


def test_metric_drift_tolerates_normal_market_movement() -> None:
    stored = [{"symbol": "AAA", "ev_to_ebitda": 15.0, "gross_margin_pct": 40.0}]
    fresh = [{"symbol": "AAA", "ev_to_ebitda": 15.4, "gross_margin_pct": 38.5}]

    assert sanity._metric_drift(fresh, stored) == []


def test_metric_drift_still_flags_a_real_disagreement() -> None:
    stored = [{"symbol": "AAA", "ev_to_ebitda": 15.0}]
    fresh = [{"symbol": "AAA", "ev_to_ebitda": 19.0}]

    assert sanity._metric_drift(fresh, stored) == ["AAA.ev_to_ebitda"]


def test_hedgefollow_check_compares_flags(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    symbols = [f"HF{i}" for i in range(300)]
    store.replace_stocks(
        [{"symbol": symbol, "hedge_fund_buys": 1} for symbol in symbols]
    )

    monkeypatch.setattr(
        sanity, "fetch_largest_buys", lambda fetch=None: dict.fromkeys(symbols, 1.0)
    )
    assert sanity.check_hedgefollow(store).ok is True

    monkeypatch.setattr(
        sanity,
        "fetch_largest_buys",
        lambda fetch=None: dict.fromkeys(symbols[:50], 1.0),
    )
    assert sanity.check_hedgefollow(store).ok is False

    monkeypatch.setattr(sanity, "fetch_largest_buys", lambda fetch=None: None)
    unavailable = sanity.check_hedgefollow(store)
    assert unavailable.ok is False
    assert "token or payload changed" in unavailable.detail


def test_hedgefollow_network_failure_is_unverifiable_not_a_divergence(
    tmp_path,
) -> None:
    """A DNS/timeout outage must never produce the app's divergence banner."""
    store = SQLiteStore(db_path=tmp_path / "test.db")

    def unreachable(url: str, data: bytes | None = None) -> str:
        raise OSError("<urlopen error [Errno -2] Name or service not known>")

    result = sanity.check_hedgefollow(store, fetch=unreachable)

    assert result.ok is None
    assert "unreachable" in result.detail


def test_gurufocus_lynch_check_recomputes_lynch_values(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    rows = []
    for index in range(3):
        eps = 2.0 + index
        growth = 15.0
        fair = lynch_fair_value(eps, growth)
        rows.append(
            {
                "symbol": f"GF{index}",
                "market_cap": 1000.0 - index,
                "price": 20.0,
                "eps_ttm": eps,
                "eps_growth_5y_pct": growth,
                "lynch_fair_value": fair,
                "lynch_upside_pct": upside_pct(fair, 20.0),
            }
        )
    store.replace_stocks(rows)
    assert sanity.check_gurufocus_lynch(store).ok is True

    broken = dict(rows[1], lynch_fair_value=1.0)
    store.replace_stocks([rows[0], broken, rows[2]])
    result = sanity.check_gurufocus_lynch(store)
    assert result.ok is False
    assert "GF1" in result.detail


def test_parse_portfolio_visualizer_reads_the_summary() -> None:
    page = """
    <table><tr><td>Annualized Return (CAGR)</td><td>9.39%</td><td>14.82%</td></tr>
    <tr><td>Standard Deviation</td><td>10.86%</td><td>16.2%</td></tr>
    <tr><td>Best Year</td><td>22.27%</td><td>31.49%</td></tr>
    <tr><td>Worst Year</td><td>-16.15%</td><td>-18.11%</td></tr></table>
    """
    metrics = sanity.parse_portfolio_visualizer(page)
    assert metrics == {
        "cagr_pct": 9.39,
        "stdev_pct": 10.86,
        "best_year_pct": 22.27,
        "worst_year_pct": -16.15,
    }


def test_portfoliovisualizer_check_compares_both_engines(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    _seed_portfolio(store)
    ours = sanity.run_backtest(store, ["SPY", "BND"], [60.0, 40.0], start="2017-01")
    page = (
        "<p>Annualized Return (CAGR) "
        f"{ours['cagr_pct']:.2f}% 14.82% Standard Deviation "
        f"{ours['stdev_pct']:.2f}% 16.31% Best Year {ours['best_year_pct']:.2f}% "
        f"Worst Year {ours['worst_year_pct']:.2f}%</p>"
    )
    result = sanity.check_portfoliovisualizer(store, post=lambda url, data: page)
    assert result.ok is True

    drifted = sanity.check_portfoliovisualizer(
        store,
        post=lambda url, data: "<p>Annualized Return (CAGR) 1.00% 15.00%</p>",
    )
    assert drifted.ok is False
    assert "CAGR" in drifted.detail


def test_portfoliovisualizer_check_flags_a_changed_page(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    _seed_portfolio(store)
    result = sanity.check_portfoliovisualizer(
        store, post=lambda url, data: "<p>Something else entirely</p>"
    )
    assert result.ok is False
    assert "no CAGR" in result.detail


def test_run_sanity_checks_isolates_a_failing_platform(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(sanity, "check_stockanalysis", explode)
    monkeypatch.setattr(
        sanity,
        "check_hedgefollow",
        lambda store, fetch=None: CheckResult("HedgeFollow", "x", True, "ok"),
    )
    monkeypatch.setattr(
        sanity,
        "check_gurufocus_dcf",
        lambda store, sample_size=50: CheckResult("GuruFocus", "DCF model", True, "ok"),
    )
    monkeypatch.setattr(
        sanity,
        "check_gurufocus_lynch",
        lambda store, sample_size=50: CheckResult(
            "GuruFocus", "Peter Lynch model", True, "ok"
        ),
    )
    monkeypatch.setattr(
        sanity,
        "check_portfoliovisualizer",
        lambda store, post=None, fetch=None: CheckResult("PV", "x", True, "ok"),
    )

    results = sanity.run_sanity_checks(store)
    assert len(results) == 5
    assert results[0].ok is False
    assert "boom" in results[0].detail


def test_report_round_trip_and_freshness(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    assert sanity.load_report(store) is None
    assert sanity.report_is_fresh(None) is False

    sanity.save_report(store, [CheckResult("A", "b", False, "c")], checked_at=100.0)
    report = sanity.load_report(store)
    assert report is not None
    assert report["results"][0]["platform"] == "A"
    assert sanity.report_is_fresh(report, now=200.0) is True
    assert sanity.report_is_fresh(report, now=1000.0) is False

    store.save_metadata(sanity.REPORT_KEY, "not json")
    assert sanity.load_report(store) is None
    store.save_metadata(sanity.REPORT_KEY, json.dumps({"results": "nope"}))
    assert sanity.load_report(store) is None


def test_save_report_records_the_next_check_time(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")

    sanity.save_report(store, [], checked_at=1000.0)

    report = sanity.load_report(store)
    assert report is not None
    assert report["next_check_at"] == 1900.0


def test_save_report_uses_the_supplied_next_check_time(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")

    sanity.save_report(store, [], checked_at=1000.0, next_check_at=1090.0)

    report = sanity.load_report(store)
    assert report is not None
    assert report["next_check_at"] == 1090.0


def _report(results: list[dict[str, Any]], checked_at: float) -> dict[str, Any]:
    return {"checked_at": checked_at, "results": results}


def test_compatibility_uses_fresh_sanity_report() -> None:
    report = _report(
        [{"platform": "StockAnalysis", "ok": True, "detail": "ok"}], time.time()
    )
    badge = sanity.compatibility(report)
    assert badge.level == "ok"
    assert badge.label == "Platforms in sync"


def test_compatibility_hover_shows_when_the_next_check_is_due() -> None:
    report = _report([{"platform": "A", "ok": True, "detail": "ok"}], 1000.0)
    report["next_check_at"] = 1900.0

    badge = sanity.compatibility(report, now=1300.0)

    assert "Last checked 5m ago." in badge.detail
    assert "Next check in 10m." in badge.detail


def test_compatibility_describes_a_sub_minute_wait() -> None:
    report = _report([{"platform": "A", "ok": True, "detail": "ok"}], 1000.0)
    report["next_check_at"] = 1045.0

    badge = sanity.compatibility(report, now=1000.0)

    assert "Next check in <1m." in badge.detail


def test_compatibility_names_a_diverged_platform() -> None:
    report = _report(
        [{"platform": "StockAnalysis", "ok": False, "detail": "field renamed"}],
        time.time(),
    )
    badge = sanity.compatibility(report)
    assert badge.level == "fail"
    assert "StockAnalysis" in badge.label
    assert "field renamed" in badge.detail


def test_compatibility_ignores_unverifiable_checks() -> None:
    report = _report(
        [{"platform": "GuruFocus", "ok": None, "detail": "blocked"}], time.time()
    )
    assert sanity.compatibility(report).level == "unknown"


def test_compatibility_is_unknown_for_a_stale_or_missing_report() -> None:
    stale = _report(
        [{"platform": "StockAnalysis", "ok": True, "detail": "ok"}],
        time.time() - 15 * 60 - 1,
    )
    assert sanity.compatibility(stale).label == "Checks pending"
    assert sanity.compatibility(None).level == "unknown"
