"""Ten-year Treasury yield, the input behind GuruFocus's DCF discount rate.

GuruFocus discounts its DCF projections at ``ceil(10Y yield) + 6%``, so the
rate has to follow the market instead of being a constant. The yield is read
from Yahoo's ``^TNX`` quote, the same series GuruFocus quotes, with FRED's
daily CSV as a fallback. Neither source needs an API key.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import urllib.request
from collections.abc import Callable

logger = logging.getLogger(__name__)

YAHOO_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?range=5d&interval=1d"
)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
REQUEST_TIMEOUT = 15
# Anything outside this range is a broken quote, not a yield.
MIN_PLAUSIBLE_YIELD = 0.0
MAX_PLAUSIBLE_YIELD = 25.0


def _usable(value: float | None) -> float | None:
    if value is None or not MIN_PLAUSIBLE_YIELD < value < MAX_PLAUSIBLE_YIELD:
        return None
    return value


def _fetch_text(url: str) -> str:
    """GET a text payload."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; stonks)"}
    )
    with urllib.request.urlopen(  # nosec B310 - URLs are fixed https constants
        request, timeout=REQUEST_TIMEOUT
    ) as response:
        payload = response.read()
    return str(payload.decode("utf-8", errors="replace"))


def parse_yahoo_yield(payload: str) -> float | None:
    """Return the latest close from a Yahoo ``^TNX`` chart payload."""
    try:
        closes = json.loads(payload)["chart"]["result"][0]["indicators"]["quote"][0][
            "close"
        ]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None
    for close in reversed(closes):
        if isinstance(close, (int, float)):
            return _usable(float(close))
    return None


def parse_fred_yield(payload: str) -> float | None:
    """Return the most recent yield from a FRED ``DGS10`` CSV payload.

    FRED writes rows as ``date,value`` and leaves holiday gaps as ``.``.
    """
    latest: float | None = None
    for row in csv.reader(io.StringIO(payload)):
        if len(row) != 2 or not row[0][:1].isdigit():
            continue  # header and blank lines
        try:
            latest = float(row[1])
        except ValueError:
            continue  # "." for holidays
    return _usable(latest)


# Tried in order; the first source that yields a plausible number wins.
SOURCES: tuple[tuple[str, Callable[[str], float | None]], ...] = (
    (YAHOO_URL, parse_yahoo_yield),
    (FRED_URL, parse_fred_yield),
)


def fetch_treasury_yield_pct(fetch: Callable[[str], str] | None = None) -> float | None:
    """Fetch the latest ten-year Treasury yield in percent.

    A dead source is not fatal: the next one is tried, and the DCF falls back
    to its default discount rate rather than blocking a whole sync.

    Args:
        fetch: Optional text fetcher, for tests.

    Returns:
        The latest yield in percent, or ``None`` when no source answers.
    """
    get = fetch or _fetch_text
    for url, parse in SOURCES:
        try:
            yield_pct = parse(get(url))
        except OSError as exc:
            logger.warning("Treasury source %s failed: %s", url, exc)
            continue
        if yield_pct is not None:
            return yield_pct
    logger.warning("No usable 10Y Treasury yield; using the default discount rate")
    return None
