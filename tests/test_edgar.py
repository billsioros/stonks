"""Tests for the rate-limited, cached EDGAR client."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from stonks import edgar, edgar_parse
from stonks.store import SQLiteStore

_FIXTURE = Path(__file__).parent / "fixtures" / "edgar" / "company_tickers.json"
COMPANY_TICKERS = json.loads(_FIXTURE.read_text(encoding="utf-8"))
EFTS_URL = "https://efts.sec.gov/LATEST/search-index?q=test"
USER_AGENT = "stonks/2.5.0 (dev@example.com)"


class FakeResponse:
    """The complete response contract the injected fetch must provide."""

    def __init__(
        self,
        payload: Any = None,
        *,
        status_code: int = 200,
        text: str = "",
        broken: bool = False,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self._broken = broken

    def json(self) -> Any:
        if self._broken:
            raise ValueError("not json")
        return self._payload


def fetch_recorder(
    response: FakeResponse,
) -> tuple[Any, list[tuple[str, dict[str, str], float]]]:
    """Record the injected fetch's contract arguments and return `response`."""
    calls: list[tuple[str, dict[str, str], float]] = []

    def fetch(url: str, headers: dict[str, str], timeout: float) -> FakeResponse:
        calls.append((url, headers, timeout))
        return response

    return fetch, calls


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(db_path=tmp_path / "edgar.db")


@pytest.fixture(autouse=True)
def configured_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDGAR_USER_AGENT", USER_AGENT)


def test_resolve_cik_pads_and_is_case_insensitive(store: SQLiteStore) -> None:
    # The plan's "320193 -> 0000320192" example is off by one: zero-padding
    # the real Apple CIK 320193 gives 0000320193.
    fetch, calls = fetch_recorder(FakeResponse(COMPANY_TICKERS))

    assert edgar.resolve_cik("AAPL", store=store, fetch=fetch) == "0000320193"
    assert edgar.resolve_cik("nflx", store=store, fetch=fetch) == "0001065280"
    assert calls == [(edgar.TICKER_MAP_URL, {"User-Agent": USER_AGENT}, 10.0)]


def test_unknown_ticker_returns_none(store: SQLiteStore) -> None:
    fetch, calls = fetch_recorder(FakeResponse(COMPANY_TICKERS))

    assert edgar.resolve_cik("ZZZZ", store=store, fetch=fetch) is None
    assert len(calls) == 1


def test_cached_cik_avoids_a_second_fetch(store: SQLiteStore) -> None:
    fetch, calls = fetch_recorder(FakeResponse(COMPANY_TICKERS))

    assert edgar.resolve_cik("AAPL", store=store, fetch=fetch) == "0000320193"
    assert edgar.resolve_cik("AAPL", store=store, fetch=fetch) == "0000320193"
    assert len(calls) == 1


def test_403_raises_edgar_unavailable(store: SQLiteStore) -> None:
    fetch, _ = fetch_recorder(FakeResponse(status_code=403, text="Forbidden"))

    with pytest.raises(edgar.EdgarUnavailable):
        edgar.resolve_cik("AAPL", store=store, fetch=fetch)
    assert store.cache_get("edgar:cik:map") is None


def test_efts_429_and_timeout_are_unavailable(store: SQLiteStore) -> None:
    rate_limited, _ = fetch_recorder(
        FakeResponse(status_code=429, text="Too Many Requests")
    )
    with pytest.raises(edgar.EdgarUnavailable):
        edgar.edgar_json(
            EFTS_URL,
            store=store,
            cache_key="edgar:test:429",
            ttl_seconds=604800,
            fetch=rate_limited,
        )

    def timeout(url: str, headers: dict[str, str], timeout: float) -> FakeResponse:
        raise httpx.TimeoutException("timed out")

    with pytest.raises(edgar.EdgarUnavailable):
        edgar.edgar_json(
            EFTS_URL,
            store=store,
            cache_key="edgar:test:timeout",
            ttl_seconds=604800,
            fetch=timeout,
        )


def test_limiter_never_exceeds_eight_requests_per_second(
    monkeypatch: pytest.MonkeyPatch, store: SQLiteStore
) -> None:
    now = 0.0
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return now

    def fake_sleep(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    monkeypatch.setattr(edgar, "_monotonic", fake_monotonic)
    monkeypatch.setattr(edgar, "_sleep", fake_sleep)
    monkeypatch.setattr(edgar, "_tokens", 8.0)
    monkeypatch.setattr(edgar, "_last", 0.0)
    fetch, calls = fetch_recorder(FakeResponse({"ok": True}))

    for index in range(8):
        edgar.edgar_json(
            f"https://data.sec.gov/{index}",
            store=store,
            cache_key=f"edgar:test:rate:{index}",
            ttl_seconds=60,
            fetch=fetch,
        )
    assert sleeps == []

    edgar.edgar_json(
        "https://data.sec.gov/8",
        store=store,
        cache_key="edgar:test:rate:8",
        ttl_seconds=60,
        fetch=fetch,
    )
    assert len(calls) == 9
    assert now >= 1 / 8
    assert sum(sleeps) >= 1 / 8


@pytest.mark.parametrize("value", ["", "a\nb", "x" * 201, "not-an-address"])
def test_invalid_user_agent_is_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("EDGAR_USER_AGENT", value)

    with pytest.raises(edgar.EdgarUnavailable):
        edgar.user_agent()


def test_valid_user_agent_is_read_at_call_time(
    monkeypatch: pytest.MonkeyPatch, store: SQLiteStore
) -> None:
    fetch, calls = fetch_recorder(FakeResponse({"ok": True}))
    monkeypatch.setenv("EDGAR_USER_AGENT", "stonks/1.0 (first@example.com)")
    edgar.edgar_json(
        EFTS_URL,
        store=store,
        cache_key="edgar:test:ua:1",
        ttl_seconds=60,
        fetch=fetch,
    )

    monkeypatch.setenv("EDGAR_USER_AGENT", "stonks/2.0 (second@example.com)")
    edgar.edgar_json(
        EFTS_URL,
        store=store,
        cache_key="edgar:test:ua:2",
        ttl_seconds=60,
        fetch=fetch,
    )

    assert [call[1] for call in calls] == [
        {"User-Agent": "stonks/1.0 (first@example.com)"},
        {"User-Agent": "stonks/2.0 (second@example.com)"},
    ]
    assert edgar.user_agent() == "stonks/2.0 (second@example.com)"


def test_missing_user_agent_disables_edgar(
    monkeypatch: pytest.MonkeyPatch, store: SQLiteStore
) -> None:
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    fetch, calls = fetch_recorder(FakeResponse(COMPANY_TICKERS))

    with pytest.raises(edgar.EdgarUnavailable):
        edgar.resolve_cik("AAPL", store=store, fetch=fetch)
    assert calls == []


def test_ticker_map_cache_uses_thirty_day_ttl(
    monkeypatch: pytest.MonkeyPatch, store: SQLiteStore
) -> None:
    ttls: list[tuple[str, int]] = []
    real_cache_set = store.cache_set

    def spy_cache_set(key: str, value: Any, ttl_seconds: int) -> None:
        ttls.append((key, ttl_seconds))
        real_cache_set(key, value, ttl_seconds)

    monkeypatch.setattr(store, "cache_set", spy_cache_set)
    fetch, _ = fetch_recorder(FakeResponse(COMPANY_TICKERS))

    edgar.resolve_cik("AAPL", store=store, fetch=fetch)

    assert ttls == [("edgar:cik:map", 30 * 24 * 60 * 60)]


def test_unparsable_json_is_unavailable(store: SQLiteStore) -> None:
    fetch, _ = fetch_recorder(FakeResponse(text="<html>blocked</html>", broken=True))

    with pytest.raises(edgar.EdgarUnavailable):
        edgar.edgar_json(
            EFTS_URL,
            store=store,
            cache_key="edgar:test:broken",
            ttl_seconds=60,
            fetch=fetch,
        )
    assert store.cache_get("edgar:test:broken") is None


def test_malformed_ticker_map_is_unavailable(store: SQLiteStore) -> None:
    fetch, _ = fetch_recorder(FakeResponse(["not", "a", "map"]))

    with pytest.raises(edgar.EdgarUnavailable):
        edgar.resolve_cik("AAPL", store=store, fetch=fetch)


# ── XBRL cross-check and debt maturity ladder (Task 2) ───────────────
FACTS_FIXTURE = (
    Path(__file__).parent / "fixtures" / "edgar" / "companyfacts_sample.json"
)
SAMPLE_FACTS: dict[str, Any] = json.loads(FACTS_FIXTURE.read_text(encoding="utf-8"))

CHECK_IDS = (
    "filings.revenue",
    "filings.net_income",
    "filings.operating_cash_flow",
    "filings.capex",
    "filings.shares_out",
    "filings.total_debt",
    "filings.cash",
    "filings.debt_coverage",
)


def _facts() -> dict[str, Any]:
    return copy.deepcopy(SAMPLE_FACTS)


def _set_value(
    facts: dict[str, Any], tag: str, value: float, *, namespace: str = "us-gaap"
) -> dict[str, Any]:
    facts["facts"][namespace][tag]["units"]["USD"][0]["val"] = value
    return facts


def _row(**overrides: float) -> dict[str, Any]:
    row: dict[str, Any] = {
        "revenue": 1_000_000_000.0,
        "net_income": 100_000_000.0,
        "shares_out": 241_060_000.0,
        "total_debt": 800_000_000.0,
        "cash": 50_000_000.0,
        "free_cash_flow": 60_000_000.0,
    }
    row.update(overrides)
    return row


def _statements() -> dict[str, Any]:
    return {
        "income_annual": {
            "rows": [
                {"id": "revenue", "label": "Revenue", "values": [1_000_000_000.0]},
                {"id": "netinc", "label": "Net Income", "values": [100_000_000.0]},
            ]
        },
        "cash_annual": {
            "rows": [
                {
                    "id": "CASHFROMOPS",
                    "label": "Operating Cash Flow",
                    "values": [150_000_000.0],
                },
                {
                    "id": "CAPEX",
                    "label": "Capital Expenditures",
                    "values": [-50_000_000.0],
                },
                {"id": "fcf", "label": "Free Cash Flow", "values": [60_000_000.0]},
            ]
        },
        "balance_annual": {
            "rows": [
                {
                    "id": "sharesOutTotalCommon",
                    "label": "Total Common Shares Outstanding",
                    "values": [241_060_000.0],
                },
                {"id": "debt", "label": "Total Debt", "values": [800_000_000.0]},
                {
                    "id": "cashneq",
                    "label": "Cash & Equivalents",
                    "values": [50_000_000.0],
                },
            ]
        },
    }


def _check_map(checks: list[Any]) -> dict[str, Any]:
    return {check.id: check for check in checks}


def test_latest_fact_prefers_unamended_period() -> None:
    tag = "RevenueFromContractWithCustomerExcludingAssessedTax"

    # The amended 10-K has a larger value and a later filing date; it is excluded.
    assert edgar_parse.latest_fact(_facts(), [tag], "USD") == (
        1_000_000_000.0,
        "000-2025-01",
    )
    # The inner `facts` mapping is accepted too, and aliases fall through in order.
    facts = _facts()
    del facts["facts"]["us-gaap"][tag]
    assert edgar_parse.latest_fact(facts["facts"], [tag, "Revenues"], "USD") == (
        600_000_000.0,
        "000-2021-01",
    )
    # On a full tie the 10-K wins over the 10-Q, and /A never qualifies.
    tied: dict[str, Any] = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "end": "2025-12-31",
                                "filed": "2026-02-15",
                                "form": "10-Q",
                                "val": 10.0,
                                "accn": "000-Q",
                            },
                            {
                                "end": "2025-12-31",
                                "filed": "2026-02-15",
                                "form": "10-K/A",
                                "val": 30.0,
                                "accn": "000-A",
                            },
                            {
                                "end": "2025-12-31",
                                "filed": "2026-02-15",
                                "form": "10-K",
                                "val": 20.0,
                                "accn": "000-K",
                            },
                        ]
                    }
                }
            }
        }
    }
    assert edgar_parse.latest_fact(tied, ["Revenues"], "USD") == (20.0, "000-K")


def test_filing_checks_falls_back_to_revenue_alias() -> None:
    facts = _facts()
    del facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]

    checks, conflicts = edgar_parse.filing_checks(
        _row(revenue=600_000_000.0), _statements(), facts
    )
    revenue = _check_map(checks)["filings.revenue"]
    assert revenue.status == "pass"
    assert "600,000,000" in revenue.value
    assert "us-gaap:Revenues" in revenue.evidence
    assert conflicts == []


def test_wrong_unit_is_ignored() -> None:
    facts = _facts()
    # The EUR entry has a later period than any USD entry.
    assert edgar_parse.latest_fact(
        facts, ["RevenueFromContractWithCustomerExcludingAssessedTax"], "USD"
    ) == (1_000_000_000.0, "000-2025-01")
    assert edgar_parse.latest_fact(
        facts, ["dei:EntityCommonStockSharesOutstanding"], "shares"
    ) == (241_060_000.0, "000-2025-01")
    assert (
        edgar_parse.latest_fact(
            facts, ["dei:EntityCommonStockSharesOutstanding"], "EUR"
        )
        is None
    )


def test_tolerance_boundaries_pass() -> None:
    # Exactly 1% of a 1bn filing value: 10m of headroom.
    checks, conflicts = edgar_parse.filing_checks(
        _row(revenue=1_010_000_000.0), _statements(), _facts()
    )
    assert _check_map(checks)["filings.revenue"].status == "pass"
    assert conflicts == []

    # Exactly $1m, which is above 1% of a 50m filing value, must also pass.
    facts = _set_value(_facts(), "NetIncomeLoss", 50_000_000.0)
    checks, conflicts = edgar_parse.filing_checks(
        _row(net_income=51_000_000.0), _statements(), facts
    )
    assert _check_map(checks)["filings.net_income"].status == "pass"
    assert conflicts == []


def test_two_percent_gap_is_a_failure_with_conflict_line() -> None:
    checks, conflicts = edgar_parse.filing_checks(
        _row(revenue=1_020_000_000.0), _statements(), _facts()
    )
    revenue = _check_map(checks)["filings.revenue"]
    assert revenue.status == "fail"
    assert len(conflicts) == 1
    assert "1,000,000,000" in conflicts[0]
    assert "1,020,000,000" in conflicts[0]
    assert "000-2025-01" in conflicts[0]


def test_missing_tag_is_unverified() -> None:
    checks, conflicts = edgar_parse.filing_checks(_row(), _statements(), {"facts": {}})
    assert tuple(check.id for check in checks) == CHECK_IDS
    assert all(check.status == "unverified" for check in checks)
    assert checks[0].value == "no XBRL fact"
    assert conflicts == []

    checks, conflicts = edgar_parse.filing_checks({}, {}, _facts())
    assert all(check.status == "unverified" for check in checks)
    assert checks[0].value == "no vendor value"
    assert conflicts == []


def test_vendor_sources_row_first_then_statement_alias() -> None:
    statements = _statements()
    statements["income_annual"]["rows"] = [
        row for row in statements["income_annual"]["rows"] if row["id"] != "revenue"
    ]
    statements["income_annual"]["rows"].append(
        {"id": "REVENUE", "label": "REVENUE", "values": [1_000_000_000.0]}
    )
    row = _row()
    del row["revenue"]
    facts = _facts()

    # Case-insensitive statement id/label fallback when the row key is absent.
    checks, conflicts = edgar_parse.filing_checks(row, statements, facts)
    assert _check_map(checks)["filings.revenue"].status == "pass"
    assert conflicts == []

    # A screener row key wins over a matching statement row.
    checks, conflicts = edgar_parse.filing_checks(
        _row(revenue=1_020_000_000.0), statements, facts
    )
    assert _check_map(checks)["filings.revenue"].status == "fail"
    assert conflicts


def test_total_debt_sums_current_and_long_term() -> None:
    checks, conflicts = edgar_parse.filing_checks(_row(), _statements(), _facts())
    assert _check_map(checks)["filings.total_debt"].status == "pass"
    assert conflicts == []

    facts = _facts()
    del facts["facts"]["us-gaap"]["DebtCurrent"]
    checks, _ = edgar_parse.filing_checks(_row(), _statements(), facts)
    assert _check_map(checks)["filings.total_debt"].status == "unverified"


def test_absent_maturity_tags_are_unverified() -> None:
    facts = _facts()
    del facts["facts"]["us-gaap"][
        "LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive"
    ]

    assert edgar_parse.maturity_ladder(facts) is None
    checks, _ = edgar_parse.filing_checks(_row(), _statements(), facts)
    coverage = _check_map(checks)["filings.debt_coverage"]
    assert coverage.status == "unverified"
    assert "no maturity ladder" in coverage.value


def test_debt_coverage_boundary() -> None:
    # Cash 50m + FCF 40m = 90m against 100m due in twelve months.
    fail_checks, _ = edgar_parse.filing_checks(
        _row(free_cash_flow=40_000_000.0), _statements(), _facts()
    )
    # Cash 50m + FCF 50m = 100m sits exactly on the boundary.
    exact_checks, _ = edgar_parse.filing_checks(
        _row(free_cash_flow=50_000_000.0), _statements(), _facts()
    )
    # Cash 50m + FCF 60m = 110m: just above the boundary.
    pass_checks, _ = edgar_parse.filing_checks(
        _row(free_cash_flow=60_000_000.0), _statements(), _facts()
    )

    assert _check_map(fail_checks)["filings.debt_coverage"].status == "fail"
    assert _check_map(exact_checks)["filings.debt_coverage"].status == "pass"
    assert _check_map(pass_checks)["filings.debt_coverage"].status == "pass"
    assert "0.90" in _check_map(fail_checks)["filings.debt_coverage"].value
    assert "1.10" in _check_map(pass_checks)["filings.debt_coverage"].value


def test_maturity_ladder_sums_five_buckets() -> None:
    expected = [
        ("0-1y", 100_000_000.0),
        ("1-2y", 80_000_000.0),
        ("2-3y", 60_000_000.0),
        ("3-4y", 40_000_000.0),
        ("4-5y", 20_000_000.0),
        ("5y+", 50_000_000.0),
    ]
    assert edgar_parse.maturity_ladder(_facts()) == expected
    ladder = edgar_parse.maturity_ladder(_facts())
    assert ladder is not None
    assert sum(
        value for label, value in ladder if not label.endswith("+")
    ) == pytest.approx(300_000_000.0)
    assert sum(value for _, value in ladder) == pytest.approx(350_000_000.0)
