"""Alert rules over consecutive screener snapshots.

Every rule compares a watched symbol's previous screener row with the freshly
fetched one. A rule never fires when either side of its comparison is missing,
and threshold rules fire only when they *become* true, so a symbol that stays
cheap does not nag on every sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Price at or below this share of the 52-week high counts as off its high.
OFF_HIGH_RATIO = 0.80
# Price at or below this multiple of the 52-week low counts as near the low.
NEAR_LOW_RATIO = 1.05
# P/E falling to this share of its previous value counts as a de-rating.
PE_DROP_RATIO = 0.85
VALUE_UPSIDE_PCT = 25.0
TARGET_UPSIDE_PCT = 25.0
# Short interest is a percentage of float, so this is percentage points.
SHORT_RISE_POINTS = 2.0
# Move from the first price seen for a symbol on a given calendar day.
DAILY_MOVE_PCT = 5.0


@dataclass(frozen=True)
class Alert:
    """One user-facing notification about a watched symbol."""

    symbol: str
    kind: str
    severity: str
    title: str
    detail: str
    dedupe_key: str


def week_bucket(now: datetime | None = None) -> str:
    """ISO week label, so a condition that stays true alerts once a week."""
    moment = now or datetime.now()
    iso = moment.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def day_bucket(now: datetime | None = None) -> str:
    """Local calendar date, so a daily move alerts at most once per day."""
    return (now or datetime.now()).date().isoformat()


def _number(row: dict[str, Any] | None, key: str) -> float | None:
    if row is None:
        return None
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def buy_opportunity(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a buy-opportunity summary when a stock trades near its 52-week low.

    "Historically low" is approximated as within 5% of the 52-week low. The
    signal is stronger when the current price is at or below both DCF and Peter
    Lynch fair value estimates.
    """
    if row is None:
        return None
    price = _number(row, "price")
    low = _number(row, "week_52_low")
    if price is None or low is None or low <= 0 or price <= 0:
        return None
    if price > low * NEAR_LOW_RATIO:
        return None

    dcf_fair = _number(row, "dcf_fair_value")
    lynch_fair = _number(row, "lynch_fair_value")
    below_both = (
        dcf_fair is not None
        and lynch_fair is not None
        and price <= dcf_fair
        and price <= lynch_fair
    )
    above_low_pct = (price / low - 1) * 100
    return {
        "symbol": str(row.get("symbol") or ""),
        "price": price,
        "week_52_low": low,
        "dcf_fair_value": dcf_fair,
        "lynch_fair_value": lynch_fair,
        "below_both_fair_values": below_both,
        "above_low_pct": above_low_pct,
    }


def buy_opportunity_alerts(
    rows: list[dict[str, Any]],
    *,
    bucket: str | None = None,
) -> list[Alert]:
    """Alerts for every stock near its 52-week low.

    Rows closest to the low come first. The signal is strongest when the price
    is also below both DCF and Peter Lynch fair value, which the title calls
    out. Dedupe is weekly via the dedupe key, and every candidate is stored so
    the app can show them all.
    """
    stamp = bucket or week_bucket()
    ranked: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        opportunity = buy_opportunity(row)
        if opportunity is None:
            continue
        ranked.append((opportunity["above_low_pct"], opportunity))

    ranked.sort(key=lambda item: item[0])
    alerts: list[Alert] = []
    for _, opportunity in ranked:
        symbol = str(opportunity["symbol"])
        title = (
            f"{symbol} is near its 52-week low and below both DCF and Peter Lynch fair value"
            if opportunity["below_both_fair_values"]
            else "Near its 52-week low"
        )
        alerts.append(
            _alert(
                symbol,
                "buy_opportunity",
                "good",
                title,
                (
                    f"Price {_fmt_alert_number(opportunity['price'])} vs 52w low "
                    f"{_fmt_alert_number(opportunity['week_52_low'])}; DCF "
                    f"{_fmt_alert_number(opportunity['dcf_fair_value'])}, Lynch "
                    f"{_fmt_alert_number(opportunity['lynch_fair_value'])}"
                ),
                stamp,
            )
        )
    return alerts


def _fmt_alert_number(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


def _alert(
    symbol: str, kind: str, severity: str, title: str, detail: str, bucket: str
) -> Alert:
    return Alert(
        symbol=symbol,
        kind=kind,
        severity=severity,
        title=title,
        detail=detail,
        dedupe_key=f"{symbol}:{kind}:{bucket}",
    )


def daily_move_alerts(
    rows: list[dict[str, Any]], state: dict[str, Any] | None, *, day: str
) -> tuple[list[Alert], dict[str, Any]]:
    """Compare today's first price with each new price, and keep the baseline.

    The first row of a day only seeds the baseline: without a full day of
    history there is no earlier price to call a sudden move from.
    """
    prices: dict[str, float] = {}
    if (
        isinstance(state, dict)
        and state.get("day") == day
        and isinstance(state.get("prices"), dict)
    ):
        prices = dict(state["prices"])

    alerts: list[Alert] = []
    for row in rows:
        symbol = str(row.get("symbol") or "")
        price = _number(row, "price")
        if not symbol or price is None or price <= 0:
            continue
        baseline = prices.get(symbol)
        if not isinstance(baseline, (int, float)) or baseline <= 0:
            prices[symbol] = price
            continue

        change = (price / float(baseline) - 1) * 100
        if abs(change) < DAILY_MOVE_PCT:
            continue
        rising = change > 0
        direction = "up" if rising else "down"
        alerts.append(
            _alert(
                symbol,
                f"daily_move_{direction}",
                "warn",
                f"{'Up' if rising else 'Down'} {abs(change):.1f}% since the day's first price",
                f"{float(baseline):.2f} → {price:.2f}",
                day,
            )
        )

    return alerts, {"day": day, "prices": prices}


def evaluate_alerts(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    bucket: str | None = None,
) -> list[Alert]:
    """Return the alerts raised by one symbol's new screener row."""
    # A symbol watched for the first time has no baseline to compare against;
    # treating NULL as zero would announce a fake move on day one.
    if previous is None:
        return []

    symbol = str(current.get("symbol") or previous.get("symbol") or "")
    stamp = bucket or week_bucket()
    alerts: list[Alert] = []

    price = _number(current, "price")
    high = _number(current, "week_52_high")
    low = _number(current, "week_52_low")
    prev_price = _number(previous, "price")
    prev_high = _number(previous, "week_52_high")
    prev_low = _number(previous, "week_52_low")

    crossed_off_high = (
        price is not None
        and high
        and prev_price is not None
        and prev_high
        and price <= high * OFF_HIGH_RATIO
        and prev_price > prev_high * OFF_HIGH_RATIO
    )
    if crossed_off_high:
        below = (1 - price / high) * 100
        alerts.append(
            _alert(
                symbol,
                "off_high",
                "good",
                f"Trading {below:.0f}% below its 52-week high",
                f"{price:.2f} vs high {high:.2f}",
                stamp,
            )
        )

    crossed_near_low = (
        price is not None
        and low
        and prev_price is not None
        and prev_low
        and price <= low * NEAR_LOW_RATIO
        and prev_price > prev_low * NEAR_LOW_RATIO
    )
    if crossed_near_low:
        alerts.append(
            _alert(
                symbol,
                "near_low",
                "good",
                "Near its 52-week low",
                f"{price:.2f} vs low {low:.2f}",
                stamp,
            )
        )

    pe = _number(current, "pe_ratio")
    prev_pe = _number(previous, "pe_ratio")
    if pe is not None and prev_pe and pe <= prev_pe * PE_DROP_RATIO:
        drop = (1 - pe / prev_pe) * 100
        alerts.append(
            _alert(
                symbol,
                "pe_drop",
                "good",
                f"P/E down {drop:.0f}% since the last sync",
                f"{pe:.1f} vs {prev_pe:.1f}",
                stamp,
            )
        )

    dcf = _number(current, "dcf_upside_pct")
    prev_dcf = _number(previous, "dcf_upside_pct")
    if (
        dcf is not None
        and dcf >= VALUE_UPSIDE_PCT
        and (prev_dcf is None or prev_dcf < VALUE_UPSIDE_PCT)
    ):
        alerts.append(
            _alert(
                symbol,
                "fair_value",
                "good",
                f"{dcf:.0f}% below DCF fair value",
                f"fair value {dcf:.1f}% upside",
                stamp,
            )
        )

    target = _number(current, "pt_upside_pct")
    prev_target = _number(previous, "pt_upside_pct")
    if (
        target is not None
        and current.get("rating")
        and target >= TARGET_UPSIDE_PCT
        and (prev_target is None or prev_target < TARGET_UPSIDE_PCT)
    ):
        alerts.append(
            _alert(
                symbol,
                "target_upside",
                "good",
                f"Analyst target implies {target:.0f}% upside",
                f're rated "{current["rating"]}"',
                stamp,
            )
        )

    short = _number(current, "short_pct")
    prev_short = _number(previous, "short_pct")
    if (
        short is not None
        and prev_short is not None
        and short - prev_short >= SHORT_RISE_POINTS
    ):
        alerts.append(
            _alert(
                symbol,
                "short_rise",
                "warn",
                f"Short interest up {short - prev_short:.1f} points",
                f"{short:.1f}% of float",
                stamp,
            )
        )

    flag = _number(current, "hedge_fund_buys")
    prev_flag = _number(previous, "hedge_fund_buys")
    if flag == 1 and prev_flag == 0:
        alerts.append(
            _alert(
                symbol,
                "hedge_fund",
                "good",
                "New in HedgeFollow's largest buys",
                "hedge fund buying flagged",
                stamp,
            )
        )

    return alerts
