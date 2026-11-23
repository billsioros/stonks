"""Tests for the rate-limited, cached EDGAR client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from stonks import edgar
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
