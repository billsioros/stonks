"""Rate-limited, cached access to SEC EDGAR JSON endpoints.

All SEC I/O goes through :func:`edgar_json` so the process-wide request limit,
the contact header and the SQLite cache are applied uniformly. The contact
string is read from the environment for every request and is never persisted.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any

import httpx

from stonks.store import SQLiteStore

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
CIK_MAP_CACHE_KEY = "edgar:cik:map"
CIK_MAP_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
REQUEST_TIMEOUT = 10.0
REQUESTS_PER_SECOND = 8

_AGENT_SHAPE = re.compile(r"([^()\r\n]+) \(([^()\r\n]+)\)")
_MAX_AGENT_LENGTH = 200

# Injectable so limiter tests can advance a fake clock without real sleeping.
_monotonic = time.monotonic
_sleep = time.sleep
_tokens = float(REQUESTS_PER_SECOND)
_last = _monotonic()
_limiter_lock = threading.Lock()


class EdgarUnavailable(RuntimeError):
    """SEC data could not be fetched or trusted."""


def user_agent() -> str:
    """Return the verified ``EDGAR_USER_AGENT`` contact string, or fail closed."""
    value = os.environ.get("EDGAR_USER_AGENT")
    if not value:
        raise EdgarUnavailable("EDGAR_USER_AGENT not configured")
    if "\r" in value or "\n" in value or len(value) > _MAX_AGENT_LENGTH:
        raise EdgarUnavailable("EDGAR_USER_AGENT is invalid")
    if value != value.strip() or not _AGENT_SHAPE.fullmatch(value):
        raise EdgarUnavailable("EDGAR_USER_AGENT must be 'name (address)' shaped")
    return value


def _wait_for_slot() -> None:
    """Consume one token, refilling at eight per second and sleeping if needed."""
    global _tokens, _last
    with _limiter_lock:
        while True:
            now = _monotonic()
            elapsed = max(0.0, now - _last)
            _tokens = min(
                float(REQUESTS_PER_SECOND),
                _tokens + elapsed * REQUESTS_PER_SECOND,
            )
            _last = now
            if _tokens >= 1.0:
                _tokens -= 1.0
                return
            _sleep((1.0 - _tokens) / REQUESTS_PER_SECOND)


def edgar_json(
    url: str,
    *,
    store: SQLiteStore,
    cache_key: str,
    ttl_seconds: int,
    fetch: Any = None,
) -> Any:
    """Return cached JSON, or fetch and cache SEC JSON from a 2xx response.

    Args:
        url: SEC JSON endpoint.
        store: SQLite store used for the JSON cache.
        cache_key: Cache key; callers use ``edgar:{cik}:{kind}``.
        ttl_seconds: Cache lifetime for a freshly fetched payload.
        fetch: Optional ``fetch(url, headers, timeout)`` callable, for tests.

    Raises:
        EdgarUnavailable: No valid contact string, or the SEC failed to answer.
    """
    cached = store.cache_get(cache_key)
    if cached is not None:
        return cached
    agent = user_agent()
    _wait_for_slot()
    getter = fetch or httpx.get
    try:
        response = getter(url, headers={"User-Agent": agent}, timeout=REQUEST_TIMEOUT)
        status = response.status_code
        if not 200 <= status < 300:
            raise EdgarUnavailable(f"SEC request failed with HTTP {status}")
        try:
            payload = response.json()
        except Exception as exc:
            # Never echo the response body: an error page may repeat the
            # contact string, which must not reach a dossier or prompt.
            raise EdgarUnavailable("SEC returned unparsable JSON") from exc
    except EdgarUnavailable:
        raise
    except Exception as exc:
        raise EdgarUnavailable("SEC request failed") from exc
    store.cache_set(cache_key, payload, ttl_seconds)
    return payload


def resolve_cik(symbol: str, *, store: SQLiteStore, fetch: Any = None) -> str | None:
    """Return the ten-digit CIK for `symbol`, or None when it is not listed.

    The full SEC ticker map is cached once, so later symbols need no request.
    """
    tickers = edgar_json(
        TICKER_MAP_URL,
        store=store,
        cache_key=CIK_MAP_CACHE_KEY,
        ttl_seconds=CIK_MAP_TTL_SECONDS,
        fetch=fetch,
    )
    if not isinstance(tickers, dict):
        raise EdgarUnavailable("SEC ticker map has an unexpected shape")
    wanted = symbol.upper()
    for entry in tickers.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("ticker") or "").upper() != wanted:
            continue
        cik = entry.get("cik_str")
        if isinstance(cik, bool) or not isinstance(cik, (int, str)):
            return None
        digits = str(cik)
        return digits.zfill(10) if digits.isdigit() else None
    return None
