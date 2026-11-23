"""Periodic cross-checks against the sites this app's data is modelled on.

Every screen, valuation and backtest in the app is a reimplementation of
something that already exists elsewhere, so each one drifts eventually: a
provider renames a field, a site changes an endpoint, a formula is edited by
mistake. These checks re-run the reference from the outside and report which
platform diverged, and by how much, so the app can show a banner instead of
quietly showing wrong numbers.

The checks are deliberately tolerant of market movement and intolerant of
structural change — they compare symbol sets, units and model outputs with
tight bounds, not exact prices. GuruFocus blocks automated reads (HTTP 403), so
its check validates the stored fair values against a fresh recomputation of the
same formulas rather than a live page.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from stonks.backtest import run_backtest
from stonks.hedgefollow import fetch_largest_buys
from stonks.presets import default_screen
from stonks.stockanalysis import fetch_rows
from stonks.store import SQLiteStore
from stonks.valuation import lynch_fair_value, upside_pct

# StockAnalysis's screener with the app's default filters returned 36 symbols
# when the screen was last verified against the site by hand.
DEFAULT_SCREEN_SIZE = 36

# A report older than this is replaced; the worker syncs hourly.
SANITY_TTL_SECONDS = 12 * 3600.0
REPORT_KEY = "sanity_report"

# Bounds. Market values move daily; these are wide enough for that and narrow
# enough to catch a unit change, a broken parser or a re-derived formula.
SCREEN_TOLERANCE_SHARE = 0.10
SCREEN_TOLERANCE_MIN = 2
# The provider pages its screener; a total at or above this bound means the
# snapshot was silently truncated rather than that the market changed.
SCREEN_MAX_ROWS = 100_000
# Spot-checked columns and the relative drift allowed between the live snapshot
# and the stored one (the two reads are hours apart, not the same instant).
DRIFT_COLUMNS = (
    "free_cash_flow",
    "net_income",
    "ev_to_ebitda",
    "shares_insiders_pct",
    "gross_margin_pct",
)
DRIFT_RELATIVE_TOLERANCE = 0.02
DRIFT_SAMPLE_SIZE = 10
HEDGE_OVERLAP_MIN = 0.60
LYNCH_RELATIVE_TOLERANCE = 0.01
PV_CAGR_TOLERANCE = 2.5
PV_STDEV_TOLERANCE = 1.0
PV_YEAR_TOLERANCE = 1.0

PORTFOLIO_VISUALIZER_URL = "https://www.portfoliovisualizer.com/backtest-portfolio"
PORTFOLIO_VISUALIZER_SYMBOLS = ("SPY", "BND")
PORTFOLIO_VISUALIZER_WEIGHTS = (60.0, 40.0)
PORTFOLIO_VISUALIZER_START = "2017-01"
PORTFOLIO_VISUALIZER_END = "2024-12"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass(frozen=True)
class CheckResult:
    """One platform's verdict. ``ok`` is False only for a real divergence."""

    platform: str
    check: str
    ok: bool | None
    detail: str


def _portfolio_visualizer_request(url: str, data: bytes | None = None) -> str:
    """POST the backtest form and return the result page as text."""
    headers = dict(_HEADERS)
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Referer"] = PORTFOLIO_VISUALIZER_URL
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(  # nosec B310 - fixed https constant
        request, timeout=90
    ) as response:
        return str(response.read().decode("utf-8", errors="replace"))


def _plain_text(page: str) -> str:
    """Strip tags and squeeze whitespace so the metrics can be matched."""
    text = re.sub(r"<[^>]+>", " ", page)
    return re.sub(r"\s+", " ", text)


_METRIC_PATTERNS = {
    "cagr_pct": r"Annualized Return \(CAGR\)\s*(-?\d+(?:\.\d+)?)%",
    "stdev_pct": r"Standard Deviation\s*(-?\d+(?:\.\d+)?)%",
    "best_year_pct": r"Best Year\s*(-?\d+(?:\.\d+)?)%",
    "worst_year_pct": r"Worst Year\s*(-?\d+(?:\.\d+)?)%",
    "max_drawdown_pct": r"Maximum Drawdown\s*(-?\d+(?:\.\d+)?)%",
}


def parse_portfolio_visualizer(page: str) -> dict[str, float]:
    """Extract the canonical portfolio's summary metrics from a result page."""
    text = _plain_text(page)
    metrics: dict[str, float] = {}
    for key, pattern in _METRIC_PATTERNS.items():
        match = re.search(pattern, text)
        if match:
            metrics[key] = float(match.group(1))
    return metrics


def check_stockanalysis(
    store: SQLiteStore,
    *,
    fetch: Callable[[str], dict] | None = None,
    discount_rate: float = 0.10,
) -> CheckResult:
    """Rebuild the default screen from live data and compare it with the store.

    A fresh provider snapshot is loaded into a scratch database and filtered
    with the same screen the app opens with; the resulting symbol set must match
    the stored one, and both must still look like the 36-symbol screen the site
    shows for those arguments.
    """
    platform = "StockAnalysis"
    screen = default_screen()
    try:
        rows = fetch_rows(fetch=fetch, discount_rate=discount_rate)
    except OSError as exc:
        return CheckResult(platform, "Default screener", None, f"unreachable: {exc}")
    if not rows:
        return CheckResult(
            platform,
            "Default screener",
            False,
            "the provider returned no rows — the payload schema or parser changed",
        )

    with tempfile.TemporaryDirectory() as directory:
        scratch = SQLiteStore(db_path=Path(directory) / "sanity.db")
        scratch.replace_stocks(rows)
        fresh, _, total = scratch.get_stocks(
            filters=screen["filters"], page_size=100_000
        )
    stored, _, stored_total = store.get_stocks(
        filters=screen["filters"], page_size=100_000
    )
    fresh_symbols = {row["symbol"] for row in fresh}
    stored_symbols = {row["symbol"] for row in stored}

    if not stored_symbols:
        return CheckResult(
            platform,
            "Default screener",
            None,
            f"no stored rows to compare yet ({total} live symbols)",
        )

    truncated = total >= SCREEN_MAX_ROWS
    added = sorted(fresh_symbols - stored_symbols)
    missing = sorted(stored_symbols - fresh_symbols)
    changed = len(added) + len(missing)
    allowed = max(
        SCREEN_TOLERANCE_MIN, round(len(stored_symbols) * SCREEN_TOLERANCE_SHARE)
    )
    drift = _metric_drift(fresh, stored)
    ok = total > 0 and changed <= allowed and not truncated and not drift
    detail = (
        f"{total} symbols now vs {stored_total} stored "
        f"(site: {DEFAULT_SCREEN_SIZE}); "
        f"{len(added)} added, {len(missing)} dropped"
    )
    if changed:
        detail += (
            f" (e.g. {'+'.join(added[:3]) or '—'} / {'-'.join(missing[:3]) or '—'})"
        )
    if truncated:
        detail += f"; truncated at {SCREEN_MAX_ROWS:,} rows"
    if drift:
        detail += f"; metric drift on {', '.join(drift[:3])}"
    return CheckResult(platform, "Default screener", ok, detail)


def _metric_drift(
    fresh: list[dict[str, Any]],
    stored: list[dict[str, Any]],
    sample_size: int = DRIFT_SAMPLE_SIZE,
) -> list[str]:
    """Symbols whose spot-checked metrics moved further than the tolerance."""
    fresh_by_symbol = {row.get("symbol"): row for row in fresh}
    drifted: list[str] = []
    checked = 0
    for row in stored:
        symbol = row.get("symbol")
        other = fresh_by_symbol.get(symbol)
        if other is None:
            continue
        checked += 1
        for column in DRIFT_COLUMNS:
            left = row.get(column)
            right = other.get(column)
            if not isinstance(left, (int, float)) or not isinstance(
                right, (int, float)
            ):
                continue
            if left == right:
                continue
            scale = max(abs(left), abs(right))
            if scale > 0 and abs(left - right) / scale > DRIFT_RELATIVE_TOLERANCE:
                drifted.append(f"{symbol}.{column}")
        if checked >= sample_size:
            break
    return drifted


def check_hedgefollow(
    store: SQLiteStore, *, fetch: Callable[..., str] | None = None
) -> CheckResult:
    """Compare the live largest-buys list with the flags stored for the screen."""
    platform = "HedgeFollow"
    buys = fetch_largest_buys(fetch)
    if not buys:
        return CheckResult(
            platform,
            "Largest HF Buys",
            False,
            "the buys list could not be read — the page token or payload changed",
        )

    stored = set(store.get_hedge_buy_symbols())
    overlap = len(stored & set(buys))
    matched = overlap / len(stored) if stored else 1.0
    ok = len(buys) >= 250 and matched >= HEDGE_OVERLAP_MIN
    detail = (
        f"{len(buys)} buys live; {overlap} of {len(stored)} stored flags still match "
        f"({matched:.0%})"
    )
    return CheckResult(platform, "Largest HF Buys", ok, detail)


def check_gurufocus_models(store: SQLiteStore, sample_size: int = 50) -> CheckResult:
    """Recompute the GuruFocus DCF/Lynch values the store already holds.

    gurufocus.com answers automated requests with 403, so this check proves the
    stored fair values still follow the published formulas from the same inputs
    — the part that drifts when the model or its units change.
    """
    platform = "GuruFocus"
    rows, _, _ = store.get_stocks(
        sort_column="market_cap", sort_ascending=False, page_size=sample_size
    )
    checked = 0
    broken: list[str] = []
    for row in rows:
        eps, growth = row.get("eps_ttm"), row.get("eps_growth_5y_pct")
        if not isinstance(eps, (int, float)) or not isinstance(growth, (int, float)):
            continue
        expected = lynch_fair_value(eps, growth)
        stored = row.get("lynch_fair_value")
        if expected is None and stored is None:
            checked += 1
            continue
        if expected is None or stored is None or stored == 0:
            broken.append(str(row.get("symbol")))
            continue
        if abs(stored - expected) > abs(expected) * LYNCH_RELATIVE_TOLERANCE:
            broken.append(str(row.get("symbol")))
            continue
        price = row.get("price")
        stored_upside = row.get("lynch_upside_pct")
        expected_upside = upside_pct(expected, price)
        if (
            stored_upside is not None
            and expected_upside is not None
            and abs(stored_upside - expected_upside) > 0.01
        ):
            broken.append(str(row.get("symbol")))
            continue
        checked += 1

    if not checked:
        return CheckResult(
            platform,
            "DCF + Peter Lynch models",
            None,
            "no stored rows with earnings and growth data to check",
        )
    ok = not broken
    detail = f"{checked} rows match the DCF / Lynch formulas"
    if broken:
        detail = f"{len(broken)} of {checked + len(broken)} rows diverge (e.g. {', '.join(broken[:3])})"
    return CheckResult(platform, "DCF + Peter Lynch models", ok, detail)


def check_portfoliovisualizer(
    store: SQLiteStore,
    *,
    post: Callable[[str, bytes], str] | None = None,
    fetch: Callable[[str], dict] | None = None,
) -> CheckResult:
    """Run a 60/40 SPY/BND portfolio on both engines and compare the metrics."""
    platform = "Portfolio Visualizer"
    data = urllib.parse.urlencode(
        {
            "timePeriod": "2",
            "startYear": PORTFOLIO_VISUALIZER_START[:4],
            "endYear": PORTFOLIO_VISUALIZER_END[:4],
            "initialAmount": "10000",
            "rebalanceType": "1",
            "benchmark": "^SP500TR",
            "symbol1": PORTFOLIO_VISUALIZER_SYMBOLS[0],
            "allocation1_1": "60",
            "symbol2": PORTFOLIO_VISUALIZER_SYMBOLS[1],
            "allocation2_1": "40",
            "portfolioName1": "Sanity",
            "reinvestDividends": "1",
            "includeYTD": "0",
        }
    ).encode()
    try:
        page = (post or _portfolio_visualizer_request)(PORTFOLIO_VISUALIZER_URL, data)
    except OSError as exc:
        return CheckResult(
            platform, "60/40 SPY+BND backtest", None, f"unreachable: {exc}"
        )

    theirs = parse_portfolio_visualizer(page)
    if "cagr_pct" not in theirs:
        return CheckResult(
            platform,
            "60/40 SPY+BND backtest",
            False,
            "the result page carried no CAGR — the form or result layout changed",
        )

    ours = run_backtest(
        store,
        list(PORTFOLIO_VISUALIZER_SYMBOLS),
        list(PORTFOLIO_VISUALIZER_WEIGHTS),
        rebalance="annual",
        start=PORTFOLIO_VISUALIZER_START,
        end=PORTFOLIO_VISUALIZER_END,
        fetch=fetch,
    )
    if "error" in ours:
        return CheckResult(platform, "60/40 SPY+BND backtest", None, ours["error"])

    differences = {
        "CAGR": abs(ours["cagr_pct"] - theirs["cagr_pct"]),
        "stdev": abs((ours["stdev_pct"] or 0) - theirs.get("stdev_pct", 0)),
        "best year": abs((ours["best_year_pct"] or 0) - theirs.get("best_year_pct", 0)),
        "worst year": abs(
            (ours["worst_year_pct"] or 0) - theirs.get("worst_year_pct", 0)
        ),
    }
    limits = {
        "CAGR": PV_CAGR_TOLERANCE,
        "stdev": PV_STDEV_TOLERANCE,
        "best year": PV_YEAR_TOLERANCE,
        "worst year": PV_YEAR_TOLERANCE,
    }
    over = {name: value for name, value in differences.items() if value > limits[name]}
    detail = (
        f"ours {ours['cagr_pct']:.2f}% CAGR / {ours['stdev_pct']:.2f}% stdev "
        f"vs {theirs['cagr_pct']:.2f}% / {theirs.get('stdev_pct', 0):.2f}%"
    )
    if over:
        detail += "; off by " + ", ".join(
            f"{name} {value:.2f}pp" for name, value in over.items()
        )
    return CheckResult(platform, "60/40 SPY+BND backtest", not over, detail)


def run_sanity_checks(
    store: SQLiteStore,
    *,
    fetch: Callable[[str], dict] | None = None,
    hedge_fetch: Callable[..., str] | None = None,
    pv_post: Callable[[str, bytes], str] | None = None,
) -> list[CheckResult]:
    """Run every check, isolating failures so one bad site cannot hide the rest."""
    results: list[CheckResult] = []
    for check in (
        lambda: check_stockanalysis(store, fetch=fetch),
        lambda: check_hedgefollow(store, fetch=hedge_fetch),
        lambda: check_gurufocus_models(store),
        lambda: check_portfoliovisualizer(store, post=pv_post, fetch=fetch),
    ):
        try:
            results.append(check())
        except Exception as exc:  # noqa: BLE001 - one site must not sink the rest
            results.append(
                CheckResult(
                    "Unknown", "sanity check", False, f"{type(exc).__name__}: {exc}"
                )
            )
    return results


def save_report(
    store: SQLiteStore,
    results: list[CheckResult],
    *,
    checked_at: float | None = None,
) -> None:
    """Persist the latest verdicts for the app's banner."""
    store.save_metadata(
        REPORT_KEY,
        json.dumps(
            {
                "checked_at": checked_at if checked_at is not None else time.time(),
                "results": [asdict(result) for result in results],
            }
        ),
    )


def load_report(store: SQLiteStore) -> dict | None:
    """Return the last report, or ``None`` when there is none or it is unreadable."""
    raw = store.get_metadata(REPORT_KEY)
    if not raw:
        return None
    try:
        report = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(report, dict) or not isinstance(report.get("results"), list):
        return None
    return report


def report_is_fresh(report: dict | None, *, now: float | None = None) -> bool:
    """Whether a report is recent enough to skip re-running the checks."""
    if not report:
        return False
    checked_at = report.get("checked_at")
    if not isinstance(checked_at, (int, float)):
        return False
    return (now if now is not None else time.time()) - checked_at < SANITY_TTL_SECONDS
