"""Tests for the screener-based alert rules."""

from datetime import datetime
from typing import Any

from stonks.alerts import evaluate_alerts, week_bucket


def _row(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "symbol": "AAA",
        "price": 100.0,
        "week_52_high": 200.0,
        "week_52_low": 90.0,
        "pe_ratio": 20.0,
        "dcf_upside_pct": 0.0,
        "lynch_upside_pct": 0.0,
        "pt_upside_pct": 0.0,
        "rating": "Buy",
        "short_pct": 1.0,
        "hedge_fund_buys": 0,
    }
    base.update(kw)
    return base


def test_week_bucket() -> None:
    assert week_bucket(datetime(2026, 11, 21)) == "2026-W47"


def test_off_high_fires_only_on_crossing() -> None:
    crossed = evaluate_alerts(_row(price=161.0), _row(price=159.0), bucket="2026-W47")
    assert [a.kind for a in crossed] == ["off_high"]
    assert crossed[0].severity == "good"
    assert crossed[0].dedupe_key == "AAA:off_high:2026-W47"
    assert "below its 52-week high" in crossed[0].title
    assert evaluate_alerts(_row(price=159.0), _row(price=158.0), bucket="b") == []


def test_near_low_fires_only_on_crossing() -> None:
    fired = evaluate_alerts(_row(price=95.0), _row(price=93.0), bucket="b")
    assert [a.kind for a in fired] == ["near_low"]
    assert evaluate_alerts(_row(price=93.0), _row(price=91.0), bucket="b") == []


def test_pe_drop_needs_both_sides() -> None:
    fired = evaluate_alerts(_row(pe_ratio=20.0), _row(pe_ratio=16.0), bucket="b")
    assert [a.kind for a in fired] == ["pe_drop"]
    assert evaluate_alerts(_row(pe_ratio=None), _row(pe_ratio=16.0), bucket="b") == []


def test_fair_value_and_target_upside() -> None:
    fired = evaluate_alerts(_row(), _row(dcf_upside_pct=30.0), bucket="b")
    assert [a.kind for a in fired] == ["fair_value"]
    fired = evaluate_alerts(_row(), _row(pt_upside_pct=40.0), bucket="b")
    assert [a.kind for a in fired] == ["target_upside"]
    assert [a.severity for a in fired] == ["good"]
    assert (
        evaluate_alerts(_row(), _row(pt_upside_pct=40.0, rating=None), bucket="b") == []
    )


def test_short_rise_and_big_move_are_warnings() -> None:
    short = evaluate_alerts(_row(short_pct=1.0), _row(short_pct=4.0), bucket="b")
    assert [(a.kind, a.severity) for a in short] == [("short_rise", "warn")]
    moved = evaluate_alerts(_row(price=100.0), _row(price=108.0), bucket="b")
    assert [(a.kind, a.severity) for a in moved] == [("big_move", "warn")]


def test_hedge_fund_flag_turns_on() -> None:
    fired = evaluate_alerts(
        _row(hedge_fund_buys=0), _row(hedge_fund_buys=1), bucket="b"
    )
    assert [a.kind for a in fired] == ["hedge_fund"]
    assert (
        evaluate_alerts(_row(hedge_fund_buys=1), _row(hedge_fund_buys=1), bucket="b")
        == []
    )
    assert (
        evaluate_alerts(_row(hedge_fund_buys=None), _row(hedge_fund_buys=1), bucket="b")
        == []
    )


def test_new_watchlist_symbol_produces_nothing() -> None:
    assert (
        evaluate_alerts(None, _row(price=150.0, dcf_upside_pct=50.0), bucket="b") == []
    )


def test_null_sides_are_skipped() -> None:
    assert evaluate_alerts(_row(price=None), _row(price=120.0), bucket="b") == []
    assert evaluate_alerts(_row(pe_ratio=20.0), _row(pe_ratio=None), bucket="b") == []


def test_bucket_defaults_to_current_week() -> None:
    fired = evaluate_alerts(_row(price=161.0), _row(price=159.0))
    assert fired[0].dedupe_key == f"AAA:off_high:{week_bucket()}"


def test_buy_opportunity_flags_near_52w_low() -> None:
    from stonks.alerts import buy_opportunity

    row = _row(price=94.0, week_52_low=90.0, dcf_fair_value=None, lynch_fair_value=None)
    opp = buy_opportunity(row)
    assert opp is not None
    assert opp["symbol"] == "AAA"
    assert opp["below_both_fair_values"] is False


def test_buy_opportunity_highlights_below_both_fair_values() -> None:
    from stonks.alerts import buy_opportunity

    row = _row(
        price=94.0,
        week_52_low=90.0,
        dcf_fair_value=120.0,
        lynch_fair_value=110.0,
    )
    opp = buy_opportunity(row)
    assert opp is not None
    assert opp["below_both_fair_values"] is True


def test_buy_opportunity_ignores_missing_or_not_low() -> None:
    from stonks.alerts import buy_opportunity

    assert buy_opportunity(_row(price=120.0, week_52_low=90.0)) is None
    assert buy_opportunity(_row(price=None, week_52_low=90.0)) is None
    assert buy_opportunity(_row(price=94.0, week_52_low=None)) is None
    assert buy_opportunity(_row(price=94.0, week_52_low=0)) is None


def test_buy_opportunity_alerts_select_strong_candidates() -> None:
    from stonks.alerts import buy_opportunity_alerts

    rows = [
        _row(
            symbol="BOTH",
            price=94.0,
            week_52_low=90.0,
            dcf_fair_value=120.0,
            lynch_fair_value=110.0,
        ),
        _row(
            symbol="NEAR",
            price=94.0,
            week_52_low=90.0,
            dcf_fair_value=None,
            lynch_fair_value=None,
        ),
        _row(
            symbol="HIGH",
            price=120.0,
            week_52_low=90.0,
            dcf_fair_value=200.0,
            lynch_fair_value=200.0,
        ),
    ]

    alerts = buy_opportunity_alerts(rows, bucket="2026-W48", cap=10)

    assert [a.symbol for a in alerts] == ["BOTH"]
    assert alerts[0].kind == "buy_opportunity"
    assert alerts[0].severity == "good"
    assert alerts[0].dedupe_key == "BOTH:buy_opportunity:2026-W48"
    assert "below both DCF and Peter Lynch" in alerts[0].title


def test_buy_opportunity_alerts_are_capped() -> None:
    from stonks.alerts import buy_opportunity_alerts

    rows = [
        _row(
            symbol=f"S{i}",
            price=94.0,
            week_52_low=90.0,
            dcf_fair_value=120.0,
            lynch_fair_value=110.0,
        )
        for i in range(5)
    ]

    alerts = buy_opportunity_alerts(rows, bucket="2026-W48", cap=2)

    assert len(alerts) == 2
