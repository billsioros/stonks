"""GuruFocus-style fair value models computed from screener fundamentals.

Two models are reimplemented here, following GuruFocus's published defaults:

* DCF — a two-stage discounted earnings model: ten years of growth then ten
  years of terminal growth, discounted back to today.
* Peter Lynch fair value — trailing EPS times the five-year earnings growth
  rate, i.e. the price at which the PEG ratio equals one.

The discount rate follows GuruFocus: the ten-year Treasury yield rounded up to
whole percent plus a 6% equity risk premium. The remaining deviation is an
input the bulk provider does not expose — the Peter Lynch model uses five-year
earnings-per-share growth where GuruFocus uses five-year EBITDA-per-share
growth.
"""

from __future__ import annotations

import math

# GuruFocus DCF defaults.
DCF_GROWTH_YEARS = 10
DCF_TERMINAL_YEARS = 10
DCF_TERMINAL_GROWTH = 0.04
DCF_MIN_GROWTH = 0.05
DCF_MAX_GROWTH = 0.20
# ceil(10Y Treasury) + 6% equity risk premium, bounded to keep a broken yield
# quote from producing meaningless valuations.
DCF_RISK_PREMIUM = 0.06
DCF_MIN_DISCOUNT_RATE = 0.06
DCF_MAX_DISCOUNT_RATE = 0.20
# Fallback when the Treasury yield cannot be fetched.
DCF_DISCOUNT_RATE = 0.10

# GuruFocus Peter Lynch bounds: growth above 25% is capped, below 5% the fair
# value is not calculated at all.
LYNCH_MIN_GROWTH_PCT = 5.0
LYNCH_MAX_GROWTH_PCT = 25.0


def _number(value: object) -> float | None:
    """Return ``value`` as a float, or ``None`` when it is not a real number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def dcf_discount_rate(treasury_yield_pct: object) -> float:
    """Discount rate from the ten-year Treasury yield, as GuruFocus sets it.

    Args:
        treasury_yield_pct: Ten-year Treasury yield in percent, e.g. ``5.07``.
            Rounded up to a whole percent before the risk premium is added.

    Returns:
        The discount rate as a fraction, or the fixed fallback when no yield
        is available.
    """
    treasury = _number(treasury_yield_pct)
    if treasury is None:
        return DCF_DISCOUNT_RATE
    rate = math.ceil(treasury) / 100 + DCF_RISK_PREMIUM
    return min(max(rate, DCF_MIN_DISCOUNT_RATE), DCF_MAX_DISCOUNT_RATE)


def dcf_fair_value(
    eps: object,
    growth_rate_pct: object,
    discount_rate: float = DCF_DISCOUNT_RATE,
) -> float | None:
    """Intrinsic value per share from a two-stage discounted earnings model.

    Args:
        eps: Current (trailing) earnings per share.
        growth_rate_pct: Growth stage growth rate, in percent.
        discount_rate: Discount rate as a fraction, e.g. ``0.10`` for 10%.

    Returns:
        Fair value per share, or ``None`` when an input is missing or earnings
        are not positive.
    """
    earnings = _number(eps)
    growth = _number(growth_rate_pct)
    if earnings is None or growth is None or earnings <= 0:
        return None

    growth_stage = min(max(growth / 100, DCF_MIN_GROWTH), DCF_MAX_GROWTH)
    value = 0.0
    for year in range(1, DCF_GROWTH_YEARS + 1):
        cash = earnings * (1 + growth_stage) ** year
        value += cash / (1 + discount_rate) ** year

    terminal_start = earnings * (1 + growth_stage) ** DCF_GROWTH_YEARS
    for year in range(1, DCF_TERMINAL_YEARS + 1):
        cash = terminal_start * (1 + DCF_TERMINAL_GROWTH) ** year
        value += cash / (1 + discount_rate) ** (DCF_GROWTH_YEARS + year)

    return value


def lynch_fair_value(eps: object, growth_rate_pct: object) -> float | None:
    """Peter Lynch fair value per share, the price at which PEG equals one.

    Args:
        eps: Current (trailing) earnings per share.
        growth_rate_pct: Five-year earnings growth rate, in percent.

    Returns:
        Fair value per share, or ``None`` when an input is missing, earnings
        are not positive, or growth is below the 5% floor GuruFocus applies.
    """
    earnings = _number(eps)
    growth = _number(growth_rate_pct)
    if earnings is None or growth is None or earnings <= 0:
        return None
    if growth < LYNCH_MIN_GROWTH_PCT:
        return None
    return earnings * min(growth, LYNCH_MAX_GROWTH_PCT)


def upside_pct(fair_value: object, price: object) -> float | None:
    """Percentage the current price sits below (positive) or above (negative)."""
    value = _number(fair_value)
    current = _number(price)
    if value is None or current is None or current <= 0:
        return None
    return (value / current - 1) * 100
