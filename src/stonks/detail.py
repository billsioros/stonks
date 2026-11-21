"""Per-symbol StockAnalysis pages: payload resolution, fetching and caching.

Each detail page is served as a SvelteKit ``__data.json`` payload in devalue
format: one flat array whose root value sits at index 0, where facts are stored
as indices into that same array. Resolving it needs care — see
``resolve_payload`` — because a number that *is* the value lives in the array
as a literal and must not be dereferenced a second time.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from stonks.stockanalysis import fetch_json
from stonks.store import SQLiteStore

BASE_URL = "https://stockanalysis.com/stocks"

PAGES = ("overview", "statistics", "forecast", "financials")
STATEMENTS = ("income-statement", "balance-sheet", "cash-flow-statement", "ratios")

# Numbers change intraday, statements only when a quarter is reported.
CACHE_TTL_SECONDS: dict[str, float] = {
    "overview": 900.0,
    "statistics": 900.0,
    "forecast": 900.0,
    "financials": 86400.0,
}


def page_url(
    symbol: str,
    page: str,
    *,
    statement: str = "income-statement",
    quarterly: bool = False,
) -> str:
    """Build the ``__data.json`` URL for one symbol page."""
    if page not in PAGES:
        raise ValueError(f"unknown page: {page}")
    slug = symbol.strip().lower()
    if page == "financials":
        if statement not in STATEMENTS:
            raise ValueError(f"unknown statement: {statement}")
        url = f"{BASE_URL}/{slug}/financials/{statement}/__data.json"
        return f"{url}?p=quarterly" if quarterly else url
    if page == "overview":
        return f"{BASE_URL}/{slug}/__data.json"
    return f"{BASE_URL}/{slug}/{page}/__data.json"


def cache_key(
    symbol: str,
    page: str,
    *,
    statement: str = "income-statement",
    period: str = "annual",
) -> str:
    """Cache key for one symbol page; the statement only applies to financials."""
    key_statement = statement if page == "financials" else "-"
    return f"sym:{symbol.strip().upper()}:{page}:{key_statement}:{period}"


def resolve_payload(payload: Any) -> Any:
    """Resolve a SvelteKit/devalue ``__data.json`` payload into plain Python.

    Values found in the flat array are literals; integers found *inside* dicts
    and lists are indices into that array. Negative or out-of-range indices and
    reference cycles resolve to ``None``.
    """
    if not isinstance(payload, dict) or payload.get("type") != "data":
        return None
    nodes = payload.get("nodes") or []
    if len(nodes) < 3 or not isinstance(nodes[2], dict):
        return None
    array = nodes[2].get("data")
    if not isinstance(array, list) or not array:
        return None

    memo: dict[int, Any] = {}

    def walk(node: Any, stack: tuple[int, ...]) -> Any:
        if isinstance(node, dict):
            return {key: walk(child, stack) for key, child in node.items()}
        if isinstance(node, list):
            return [walk(child, stack) for child in node]
        if isinstance(node, bool) or node is None:
            return node
        if isinstance(node, int):
            return value_at(node, stack)
        return node

    def value_at(index: int, stack: tuple[int, ...]) -> Any:
        if index < 0 or index >= len(array):
            return None
        if index in memo:
            return memo[index]
        if index in stack:
            return None
        raw = array[index]
        if not isinstance(raw, (dict, list)):
            # A literal number/string/bool/null, not a reference.
            memo[index] = raw
            return raw
        resolved = walk(raw, (*stack, index))
        memo[index] = resolved
        return resolved

    return value_at(0, ())


def load_page(
    store: SQLiteStore,
    symbol: str,
    page: str,
    *,
    statement: str = "income-statement",
    period: str = "annual",
    force: bool = False,
    fetch: Callable[[str], dict[str, Any]] | None = None,
) -> tuple[Any, float | None]:
    """Load one symbol page, from cache when warm.

    Returns ``(resolved_data, fetched_at)``; both are ``None`` when the page
    cannot be fetched and nothing is cached. A failed fetch falls back to an
    expired cache entry so a stale page still renders.
    """
    key = cache_key(symbol, page, statement=statement, period=period)
    if not force:
        fresh = store.cache_get(key)
        if isinstance(fresh, dict) and "data" in fresh:
            return fresh.get("data"), fresh.get("fetched_at")

    url = page_url(symbol, page, statement=statement, quarterly=period == "quarterly")
    try:
        resolved = resolve_payload((fetch or fetch_json)(url))
    except Exception:
        resolved = None

    if resolved is None:
        stale = store.cache_get(key, allow_expired=True)
        if isinstance(stale, dict) and "data" in stale:
            return stale.get("data"), stale.get("fetched_at")
        return None, None

    fetched_at = time.time()
    store.cache_set(
        key, {"data": resolved, "fetched_at": fetched_at}, CACHE_TTL_SECONDS[page]
    )
    return resolved, fetched_at
