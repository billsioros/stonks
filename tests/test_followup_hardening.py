"""Regression tests for the post-Phase-B hardening pass."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from stonks import dossier, edgar, edgar_parse, report, sanity, stockanalysis, worker
from stonks.store import SQLiteStore
from tests.test_edgar import _facts, _row, _statements


class _FetchResponse:
    def __init__(self, payload: Any) -> None:
        self.status_code = 200
        self.payload = payload

    def json(self) -> Any:
        return self.payload


def _stub_worker_store(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    store = MagicMock(spec=SQLiteStore)
    store.get_watchlist_symbols.return_value = []
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    monkeypatch.setattr(worker, "current_discount_rate", lambda: 0.11)
    monkeypatch.setattr(worker, "fetch_largest_buys", lambda: None)
    monkeypatch.setattr(sanity, "load_report", lambda store: None)
    return store


def test_worker_runs_sanity_checks_even_when_sync_fails(monkeypatch) -> None:
    store = _stub_worker_store(monkeypatch)
    monkeypatch.setattr(
        worker,
        "fetch_rows",
        lambda discount_rate=None: (_ for _ in ()).throw(OSError("dns")),
    )
    checks = [sanity.CheckResult("StockAnalysis", "Default screener", True, "ok")]
    ran: list[int] = []
    saved: list[list[sanity.CheckResult]] = []
    monkeypatch.setattr(
        sanity, "run_sanity_checks", lambda store: ran.append(1) or checks
    )
    monkeypatch.setattr(
        sanity, "save_report", lambda store, results: saved.append(results)
    )

    worker.job()

    assert ran == [1]
    assert saved == [checks]
    assert store.get_metadata is not None


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("discount", "Treasury yield"),
        ("rows", "StockAnalysis"),
        ("buys", "HedgeFollow"),
    ],
)
def test_sync_failure_names_the_provider(monkeypatch, source, expected) -> None:
    store = _stub_worker_store(monkeypatch)
    monkeypatch.setattr(
        worker, "fetch_rows", lambda discount_rate=None: [{"symbol": "AAA"}]
    )
    if source == "discount":
        monkeypatch.setattr(
            worker,
            "current_discount_rate",
            lambda: (_ for _ in ()).throw(OSError("<urlopen error dns>")),
        )
    elif source == "buys":
        monkeypatch.setattr(
            worker,
            "fetch_largest_buys",
            lambda: (_ for _ in ()).throw(OSError("<urlopen error dns>")),
        )
    else:
        monkeypatch.setattr(
            worker,
            "fetch_rows",
            lambda discount_rate=None: (_ for _ in ()).throw(
                OSError("<urlopen error dns>")
            ),
        )

    monkeypatch.setattr(sanity, "run_sanity_checks", lambda store: [])
    monkeypatch.setattr(sanity, "save_report", lambda store, results: None)

    worker.job()

    errors = [
        call.args[1]
        for call in store.save_metadata.call_args_list
        if call.args[0] == "last_sync_error"
    ]
    assert errors
    assert expected in errors[-1]


def test_run_sanity_checks_reports_all_four_required_targets(
    monkeypatch, tmp_path
) -> None:
    store = SQLiteStore(db_path=tmp_path / "sanity.db")

    def result(platform: str, check: str) -> sanity.CheckResult:
        return sanity.CheckResult(platform, check, True, "ok")

    monkeypatch.setattr(
        sanity,
        "check_stockanalysis",
        lambda store, **kwargs: result("StockAnalysis", "Default screener"),
    )
    monkeypatch.setattr(
        sanity,
        "check_hedgefollow",
        lambda store, **kwargs: result("HedgeFollow", "Largest HF Buys"),
    )
    monkeypatch.setattr(
        sanity,
        "check_gurufocus_dcf",
        lambda store: result("GuruFocus", "DCF model"),
    )
    monkeypatch.setattr(
        sanity,
        "check_gurufocus_lynch",
        lambda store: result("GuruFocus", "Peter Lynch model"),
    )
    monkeypatch.setattr(
        sanity,
        "check_portfoliovisualizer",
        lambda store, **kwargs: result(
            "Portfolio Visualizer", "60/40 SPY+BND backtest"
        ),
    )

    pairs = {(r.platform, r.check) for r in sanity.run_sanity_checks(store)}

    assert ("StockAnalysis", "Default screener") in pairs
    assert ("HedgeFollow", "Largest HF Buys") in pairs
    assert ("GuruFocus", "DCF model") in pairs
    assert ("GuruFocus", "Peter Lynch model") in pairs
    assert ("Unknown", "sanity check") not in pairs


def test_gurufocus_dcf_check_recomputes_the_stored_fair_value(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "sanity.db")
    rate = 0.11
    row = {
        "symbol": "AAA",
        "eps_ttm": 5.0,
        "eps_growth_10y_pct": 12.0,
        "dcf_discount_rate_pct": rate * 100,
        "dcf_fair_value": stockanalysis.dcf_fair_value(5.0, 12.0, rate),
    }
    store.replace_stocks([row])

    result = sanity.check_gurufocus_dcf(store)

    assert result.platform == "GuruFocus"
    assert result.check == "DCF model"
    assert result.ok is True

    broken = dict(row, dcf_fair_value=row["dcf_fair_value"] * 2)
    store.replace_stocks([broken])
    assert sanity.check_gurufocus_dcf(store).ok is False


def test_both_ai_reports_require_citations() -> None:
    screener = (report.SYSTEM_INSTRUCTION + report.REPORT_SECTIONS).lower()
    symbol = (report.SYMBOL_SYSTEM_INSTRUCTION + report.SYMBOL_REPORT_SECTIONS).lower()

    assert "cite" in screener and "source" in screener
    assert "cite" in symbol and "check id" in symbol
    assert "accession" in symbol


def test_malformed_cik_is_an_unavailability_error(monkeypatch) -> None:
    monkeypatch.setenv("EDGAR_USER_AGENT", "stonks test (test@example.com)")
    monkeypatch.setattr(
        edgar,
        "edgar_json",
        lambda *a, **k: {"0": {"ticker": "AAA", "cik_str": "not-a-number"}},
    )

    with pytest.raises(edgar.EdgarUnavailable, match="CIK"):
        edgar.resolve_cik("AAA", store=MagicMock(spec=SQLiteStore))


def test_statement_value_does_not_fall_back_to_ttm() -> None:
    statements = {
        "income_annual": {
            "periods": [{"is_ttm": True}],
            "rows": [{"id": "revenue", "values": [100.0]}],
        }
    }
    assert (
        edgar_parse._statement_value(statements, "income_annual", ("revenue",)) is None
    )


def test_debt_coverage_uses_the_xbrl_cash_fact_when_vendor_cash_is_missing() -> None:
    statements = _statements()
    balance = statements["balance_annual"]["rows"]
    statements["balance_annual"]["rows"] = [
        row for row in balance if row.get("id") != "cashneq"
    ]
    checks, _ = edgar_parse.filing_checks(_row(cash=None), statements, _facts())
    coverage = next(check for check in checks if check.id == "filings.debt_coverage")

    assert coverage.status == "pass"
    assert "us-gaap:CashAndCashEquivalentsAtCarryingValue" in coverage.evidence


def test_as_date_accepts_a_date_object() -> None:
    assert dossier._as_date(date(2026, 11, 23)) == date(2026, 11, 23)


def test_provenance_uses_the_newest_filing_date() -> None:
    evidence = dossier.FilingEvidence(
        cik="0000320193",
        latest_10k="2025-02-01",
        latest_10q="2026-02-01",
    )
    built = dossier.build_dossier("AAA", filing_evidence=evidence)
    sec = next(item for item in built.provenance if item[0] == "sec")

    assert "2026-02-01" in sec[2]
    assert "2025-02-01" not in sec[2]


def test_efts_cache_key_varies_with_the_requested_forms(monkeypatch, tmp_path) -> None:
    from stonks import filing_evidence

    keys: list[str] = []
    store = MagicMock(spec=SQLiteStore)

    def fake_json(url, *, store, cache_key, ttl_seconds, fetch=None):
        keys.append(cache_key)
        return {"hits": {"total": 0, "hits": []}}

    monkeypatch.setattr(filing_evidence.edgar, "edgar_json", fake_json)
    filing_evidence.search_filings("phrase", "0000320193", forms=("10-K",), store=store)
    filing_evidence.search_filings("phrase", "0000320193", forms=("10-Q",), store=store)

    assert keys[0] != keys[1]


def test_phrase_hits_keep_their_accession_in_evidence() -> None:
    hit = {
        "phrase": "material weakness",
        "count": 1,
        "filing_date": "2026-02-01",
        "accession": "000-2026-01",
        "form": "10-K",
        "url": "https://www.sec.gov/Archives/edgar/data/000-2026-01",
    }
    evidence = dossier.FilingEvidence(cik="0000320193", hits=(hit,))
    gate = dossier.filing_gate({}, {}, evidence, today="2026-02-10")
    red_flag_gate = next(g for g in (gate,) if g.key == "filings")

    assert any(
        "000-2026-01" in conflict for conflict in red_flag_gate.conflicts
    ) or any("000-2026-01" in check.evidence for check in red_flag_gate.checks)


def test_masthead_renders_badges_on_repeated_apptest_runs(
    tmp_path, monkeypatch
) -> None:
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from stonks import app

    db_path = tmp_path / "stonks.db"
    real_init = SQLiteStore.__init__

    def _init(self, db_path=db_path, *args, **kwargs):
        return real_init(self, db_path, *args, **kwargs)

    monkeypatch.setattr(SQLiteStore, "__init__", _init)
    monkeypatch.setattr(app, "get_store", lambda: SQLiteStore(db_path=db_path))
    for _ in range(2):
        st.cache_resource.clear()
        at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
        at.run()
        assert not at.exception
        html = " ".join(str(md.value) for md in at.markdown)
        assert "sk-badge" in html
        assert "Sync" in html


def test_store_get_buy_opportunities_prioritizes_below_both_fair_values(
    tmp_path,
) -> None:
    store = SQLiteStore(db_path=tmp_path / "buy.db")
    store.replace_stocks(
        [
            {
                "symbol": "LOW",
                "description": "Near low only",
                "price": 101.0,
                "week_52_low": 100.0,
                "dcf_fair_value": None,
                "lynch_fair_value": None,
            },
            {
                "symbol": "BOTH",
                "description": "Below both",
                "price": 101.0,
                "week_52_low": 100.0,
                "dcf_fair_value": 120.0,
                "lynch_fair_value": 130.0,
            },
            {
                "symbol": "NOPE",
                "description": "Not low",
                "price": 150.0,
                "week_52_low": 100.0,
                "dcf_fair_value": 200.0,
                "lynch_fair_value": 200.0,
            },
        ]
    )

    opportunities = store.get_buy_opportunities(limit=10)

    assert [row["symbol"] for row in opportunities] == ["BOTH", "LOW"]
    assert opportunities[0]["dcf_fair_value"] == 120.0
