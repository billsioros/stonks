"""Tests for the GuruFocus-style valuation models."""

import pytest

from stonks import valuation


class TestDcfFairValue:
    def test_growth_equal_to_discount_is_earnings_times_years_plus_terminal(
        self,
    ) -> None:
        # At a 10% growth stage and a 10% discount rate every growth-stage year
        # contributes exactly one dollar of present value.
        assert valuation.dcf_fair_value(1.0, 10.0) == pytest.approx(17.4412, abs=1e-3)

    def test_growth_is_clamped_to_gurufocus_bounds(self) -> None:
        capped = valuation.dcf_fair_value(3.0, 80.0)
        floor = valuation.dcf_fair_value(3.0, -10.0)

        assert capped == valuation.dcf_fair_value(3.0, 20.0)
        assert floor == valuation.dcf_fair_value(3.0, 5.0)
        assert capped > floor

    def test_negative_or_missing_earnings_yield_none(self) -> None:
        assert valuation.dcf_fair_value(-1.0, 10.0) is None
        assert valuation.dcf_fair_value(0.0, 10.0) is None
        assert valuation.dcf_fair_value(None, 10.0) is None
        assert valuation.dcf_fair_value(1.0, None) is None

    def test_higher_discount_rate_reduces_value(self) -> None:
        cheap = valuation.dcf_fair_value(2.0, 15.0, discount_rate=0.08)
        dear = valuation.dcf_fair_value(2.0, 15.0, discount_rate=0.12)

        assert cheap is not None and dear is not None
        assert cheap > dear


class TestDcfDiscountRate:
    def test_yield_is_rounded_up_then_premium_added(self) -> None:
        # GuruFocus: ceil(10Y Treasury) + 6%.
        assert valuation.dcf_discount_rate(4.92) == pytest.approx(0.11)
        assert valuation.dcf_discount_rate(5.07) == pytest.approx(0.12)
        assert valuation.dcf_discount_rate(5.14) == pytest.approx(0.12)
        assert valuation.dcf_discount_rate(5.0) == pytest.approx(0.11)

    def test_rate_is_bounded(self) -> None:
        assert valuation.dcf_discount_rate(0.0) == pytest.approx(
            valuation.DCF_MIN_DISCOUNT_RATE
        )
        assert valuation.dcf_discount_rate(45.0) == pytest.approx(
            valuation.DCF_MAX_DISCOUNT_RATE
        )

    def test_missing_yield_falls_back_to_the_default(self) -> None:
        assert valuation.dcf_discount_rate(None) == pytest.approx(
            valuation.DCF_DISCOUNT_RATE
        )


class TestLynchFairValue:
    def test_eps_times_growth_rate(self) -> None:
        assert valuation.lynch_fair_value(2.0, 20.0) == pytest.approx(40.0)

    def test_growth_above_25_percent_is_capped(self) -> None:
        assert valuation.lynch_fair_value(2.0, 30.0) == pytest.approx(50.0)

    def test_growth_below_5_percent_is_not_valued(self) -> None:
        assert valuation.lynch_fair_value(2.0, 4.9) is None

    def test_negative_or_missing_earnings_yield_none(self) -> None:
        assert valuation.lynch_fair_value(-2.0, 15.0) is None
        assert valuation.lynch_fair_value(2.0, None) is None


class TestUpsidePct:
    def test_below_fair_value_is_positive(self) -> None:
        assert valuation.upside_pct(110.0, 100.0) == pytest.approx(10.0)

    def test_above_fair_value_is_negative(self) -> None:
        assert valuation.upside_pct(80.0, 100.0) == pytest.approx(-20.0)

    def test_unusable_inputs_yield_none(self) -> None:
        assert valuation.upside_pct(None, 100.0) is None
        assert valuation.upside_pct(100.0, 0) is None
        assert valuation.upside_pct(100.0, None) is None
