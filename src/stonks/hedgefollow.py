"""HedgeFollow's "Largest Hedge Fund Buys" list, as a per-symbol flag.

https://hedgefollow.com/Largest-Hedge-Fund-Buys.php ranks the stocks institutional
investors added the most money to in the latest 13F round — 300 stocks, ordered by
the total value bought. The page is a JavaScript table: the rows arrive as JSON
from ``/ggg/web_request.php``, gated by a data token (``hf_dt``) that has to be
scraped from the HTML first and posted alongside the request.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from collections.abc import Callable, Collection
from http.cookiejar import CookieJar
from typing import Any

logger = logging.getLogger(__name__)

BUYS_PAGE_URL = "https://hedgefollow.com/Largest-Hedge-Fund-Buys.php"
REQUEST_URL = "https://hedgefollow.com/ggg/web_request.php"
REQUEST_ID = "largest_fund_buys_nl"
# The list is capped at this many rows server-side, whatever limit is asked for.
LIST_SIZE = 300
REQUEST_TIMEOUT = 30
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://hedgefollow.com",
    "Referer": BUYS_PAGE_URL,
}
_TOKEN_PATTERN = re.compile(r'hf_dt = "([^"]+)"')


class HedgeFollowUnavailable(OSError):
    """The site could not be reached, so the buys list is unknown, not empty."""


class _Session:
    """GET/POST through one cookie jar, as a browser would."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def __call__(self, url: str, data: bytes | None = None) -> str:
        headers = dict(_HEADERS)
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            headers["X-Requested-With"] = "XMLHttpRequest"
        request = urllib.request.Request(url, data=data, headers=headers)
        with self._opener.open(  # nosec B310 - URLs are fixed https constants
            request, timeout=REQUEST_TIMEOUT
        ) as response:
            payload = response.read()
        return str(payload.decode("utf-8", errors="replace"))


def parse_token(page: str) -> str | None:
    """Return the page's data token, or ``None`` when the page has no list."""
    match = _TOKEN_PATTERN.search(page)
    return match.group(1) if match else None


def request_body(token: str) -> bytes:
    """Build the form body the buys table is loaded with."""
    pairs = [
        ("params[requestId]", REQUEST_ID),
        ("params[page]", "1"),
        ("params[offset]", "0"),
        ("params[limit_per_page]", str(LIST_SIZE)),
        # The endpoint validates these two against the table's own request.
        ("params[filteredCt]", "0"),
        ("params[totalCt]", "0"),
        # The endpoint rejects a request without its filter, and 'hf' is the
        # page's default: hedge funds only, no ETFs, any market cap.
        ("params[filters][institution_type]", "hf"),
        ("params[filter_cols][institution_type]", "filler"),
        ("params[filter_checks][institution_type]", "function"),
        ("dt", token),
    ]
    return urllib.parse.urlencode(pairs).encode()


def parse_buys(payload: str) -> dict[str, float]:
    """Return ``{symbol: dollars bought}`` from the buys table's JSON payload."""
    try:
        rows = json.loads(payload)["data"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}
    if not isinstance(rows, list):
        return {}
    buys: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        value = row.get("valBuys")
        if not symbol or not isinstance(value, (int, float)):
            continue
        # valBuys is in thousands of dollars.
        buys[symbol] = float(value) * 1000
    return buys


def fetch_largest_buys(
    fetch: Callable[..., str] | None = None,
) -> dict[str, float] | None:
    """Fetch the largest hedge fund buys as ``{symbol: dollars bought}``.

    Args:
        fetch: Optional ``fetch(url, data=None)`` callable, for tests.

    Returns:
        The symbols in the list, or ``None`` when the page or payload changed.

    Raises:
        HedgeFollowUnavailable: the site could not be reached at all.
    """
    get = fetch or _Session()
    try:
        token = parse_token(get(BUYS_PAGE_URL))
        if token is None:
            logger.warning("HedgeFollow page carried no data token")
            return None
        buys = parse_buys(get(REQUEST_URL, request_body(token)))
    except OSError as exc:
        raise HedgeFollowUnavailable(str(exc)) from exc
    if not buys:
        logger.warning("HedgeFollow buys list came back empty")
        return None
    return buys


def apply_flags(rows: list[dict[str, Any]], symbols: Collection[str]) -> int:
    """Set ``hedge_fund_buys`` on each row, returning how many are in the list."""
    listed = {str(symbol).upper() for symbol in symbols}
    matched = 0
    for row in rows:
        in_list = str(row.get("symbol") or "").upper() in listed
        row["hedge_fund_buys"] = int(in_list)
        matched += in_list
    return matched
