"""Tests for the screener's filter helpers and unified screen loading."""

from stonks import app


def test_prune_filters_removes_empty_bounds_and_values() -> None:
    raw = {
        "pe_ratio": {"min": None, "max": None},
        "exchange": {"values": []},
        "market_cap": {"min": 1000},
        "valid_enum": {"values": ["NYSE"]},
    }
    pruned = app._prune_filters(raw)
    assert "pe_ratio" not in pruned
    assert "exchange" not in pruned
    assert pruned["market_cap"] == {"min": 1000}
    assert pruned["valid_enum"] == {"values": ["NYSE"]}


def test_apply_screen_state_prunes_filters_and_defaults_sort_ascending(
    monkeypatch,
) -> None:
    state: dict = {}
    monkeypatch.setattr(app.st, "session_state", state)

    app.apply_screen_state(
        {
            "filters": {
                "pe_ratio": {"min": None, "max": None},
                "symbol": {"values": ["A"]},
            },
            "view_preset": "Valuation",
            "sort_column": "pe_ratio",
        }
    )

    assert state["active_filters"] == {"symbol": {"values": ["A"]}}
    assert state["view_preset"] == "Valuation"
    assert state["sort_column"] == "pe_ratio"
    assert state["sort_ascending"] is True
    assert state["current_page"] == 1


def test_hedge_fund_flag_is_labelled_as_a_13f_whale() -> None:
    from stonks.config import COLUMN_DISPLAY_NAMES

    assert COLUMN_DISPLAY_NAMES["hedge_fund_buys"] == "13F Whale"


def test_cyclical_risk_flag_renders_a_badge() -> None:
    assert app._fmt_cyclical_risk(1) == "⚠️ Peak"


def test_column_guide_explains_the_visible_columns() -> None:
    guide = app._column_guide_markdown(["pe_ratio", "hedge_fund_buys"])
    assert "**P/E**" in guide
    assert "divided by trailing twelve-month earnings per share" in guide
    assert "**13F Whale**" in guide
    assert "45 days" in guide


def test_column_guide_skips_unknown_columns() -> None:
    assert app._column_guide_markdown(["not_a_column"]) == ""


def test_sync_time_text_tolerates_malformed_metadata() -> None:
    assert app._sync_time_text(None) == "never"
    assert app._sync_time_text("") == "never"
    assert app._sync_time_text("not-a-timestamp") == "an unknown time"
    assert app._sync_time_text("nan") == "an unknown time"
    assert app._sync_time_text("1e400") == "an unknown time"
    assert app._sync_time_text("0") != "an unknown time"
    assert app._fmt_cyclical_risk(0) == ""
    assert app._fmt_cyclical_risk(None) == "—"
