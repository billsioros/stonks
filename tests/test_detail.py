"""Tests for the per-symbol detail payload layer."""

import json
from pathlib import Path
from typing import Any

import pytest

from stonks.detail import cache_key, load_page, page_url, resolve_payload
from stonks.store import SQLiteStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(db_path=tmp_path / "test.db")


def _payload(values: list[Any]) -> dict[str, Any]:
    return {"type": "data", "nodes": [{}, {}, {"data": values}]}


# ── Payload resolution ───────────────────────────────────────────────


def test_resolve_payload_dereferences_indices() -> None:
    assert resolve_payload(_payload([{"price": 1, "name": 2}, 42.5, "NVDA"])) == {
        "price": 42.5,
        "name": "NVDA",
    }


def test_resolve_payload_keeps_literal_ints() -> None:
    # index 1 holds the literal 41; it must not be dereferenced again.
    assert resolve_payload(_payload([{"count": 1}, 41])) == {"count": 41}


def test_resolve_payload_maps_negative_and_out_of_range_to_none() -> None:
    assert resolve_payload(_payload([{"a": -1, "b": 9}, 1])) == {"a": None, "b": None}


def test_resolve_payload_breaks_cycles() -> None:
    assert resolve_payload(_payload([{"self": 1}, {"parent": 1}])) == {
        "self": {"parent": None}
    }


def test_resolve_payload_rejects_non_data_payload() -> None:
    assert resolve_payload({"type": "error"}) is None
    assert resolve_payload({}) is None
    assert resolve_payload({"type": "data", "nodes": []}) is None


def test_resolve_payload_handles_real_overview_fixture() -> None:
    payload = json.loads((FIXTURES / "nvda_overview.json").read_text())
    resolved = resolve_payload(payload)
    assert isinstance(resolved, dict)
    assert resolved["infoTable"][0]["v"] == "Semiconductors"


# ── URLs and cache keys ──────────────────────────────────────────────


def test_page_url_overview() -> None:
    assert page_url("NVDA", "overview") == (
        "https://stockanalysis.com/stocks/nvda/__data.json"
    )


def test_page_url_statistics() -> None:
    assert page_url("nvda", "statistics") == (
        "https://stockanalysis.com/stocks/nvda/statistics/__data.json"
    )


def test_page_url_financials_quarterly_statement() -> None:
    assert page_url("NVDA", "financials", statement="ratios", quarterly=True) == (
        "https://stockanalysis.com/stocks/nvda/financials/ratios/__data.json?p=quarterly"
    )


def test_cache_key_includes_statement_and_period() -> None:
    assert (
        cache_key("NVDA", "financials", statement="ratios", period="quarterly")
        == "sym:NVDA:financials:ratios:quarterly"
    )
    assert cache_key("NVDA", "overview") == "sym:NVDA:overview:-:annual"


# ── Cached loading ───────────────────────────────────────────────────


def test_load_page_fetches_then_caches(store: SQLiteStore) -> None:
    calls: list[str] = []

    def fetch(url: str) -> dict[str, Any]:
        calls.append(url)
        return _payload([{"marketCap": 1}, "3.03T"])

    data, fetched_at = load_page(store, "NVDA", "overview", fetch=fetch)
    assert data == {"marketCap": "3.03T"} and fetched_at is not None

    data2, fetched_at2 = load_page(store, "NVDA", "overview", fetch=fetch)
    assert data2 == data and fetched_at2 == fetched_at and len(calls) == 1


def test_load_page_force_refetches(store: SQLiteStore) -> None:
    payload = _payload([{"marketCap": 1}, "3.03T"])
    calls: list[str] = []

    def fetch(url: str) -> dict[str, Any]:
        calls.append(url)
        return payload

    load_page(store, "NVDA", "overview", fetch=fetch)
    load_page(store, "NVDA", "overview", force=True, fetch=fetch)
    assert len(calls) == 2


def test_load_page_falls_back_to_stale_cache_on_failure(store: SQLiteStore) -> None:
    store.cache_set(
        "sym:NVDA:overview:-:annual",
        {"data": {"marketCap": "3.03T"}, "fetched_at": 1234.0},
        ttl_seconds=-1,
    )

    def boom(url: str) -> dict[str, Any]:
        raise OSError("down")

    assert load_page(store, "NVDA", "overview", fetch=boom) == (
        {"marketCap": "3.03T"},
        1234.0,
    )


def test_load_page_returns_none_without_cache_on_failure(store: SQLiteStore) -> None:
    def boom(url: str) -> dict[str, Any]:
        raise OSError("down")

    assert load_page(store, "ZZZZ", "overview", fetch=boom) == (None, None)


def test_load_page_does_not_cache_unresolvable_payload(store: SQLiteStore) -> None:
    def fetch(url: str) -> dict[str, Any]:
        return {"type": "error"}

    assert load_page(store, "NVDA", "overview", fetch=fetch) == (None, None)
    assert store.cache_get("sym:NVDA:overview:-:annual") is None
