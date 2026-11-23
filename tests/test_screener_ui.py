"""Tests for the screener's filter helpers and unified screen loading."""

import pandas as pd

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
    assert "crowding is not a signal on its own" in guide


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


def test_screener_labels_are_self_explanatory() -> None:
    from stonks.config import COLUMN_DISPLAY_NAMES

    assert COLUMN_DISPLAY_NAMES["valuation_triangulation"] == "Model Agreement"
    assert COLUMN_DISPLAY_NAMES["valuation_upside_capped_pct"] == "Avg Upside %"
    assert COLUMN_DISPLAY_NAMES["shares_insiders_percent"] == "Insider Ownership %"
    assert COLUMN_DISPLAY_NAMES["current_ratio"] == "Current Ratio"
    assert COLUMN_DISPLAY_NAMES["fcf_margin_pct"] == "FCF Margin %"


def test_insider_ratio_appears_in_no_view_preset() -> None:
    from stonks.config import NUMERIC_FILTER_COLUMNS, VIEW_PRESETS

    for name, columns in VIEW_PRESETS.items():
        assert "shares_insiders_pct" not in columns, name
        if name in ("Overview", "Quality"):
            assert "shares_insiders_percent" in columns

    # The raw ratio stays filterable; it is only hidden as a display column.
    assert "shares_insiders_pct" in NUMERIC_FILTER_COLUMNS
    assert "shares_insiders_percent" in NUMERIC_FILTER_COLUMNS


def test_upside_cells_carry_their_direction() -> None:
    assert app._fmt_upside(18.4) == "🟢 +18.4%"
    assert app._fmt_upside(-12.0) == "🔴 -12.0%"
    assert app._fmt_upside(None) == "—"
    assert app._fmt_upside(float("nan")) == "—"


def test_whale_flag_renders_a_whale_only_when_flagged() -> None:
    assert app._fmt_flag(1) == "🐋"
    assert app._fmt_flag(0) == "—"
    assert app._fmt_flag(None) == "—"


def test_current_ratio_marks_tight_liquidity() -> None:
    assert app._fmt_current_ratio(0.82) == "🔴 0.82"
    assert app._fmt_current_ratio(1.4) == "1.40"
    assert app._fmt_current_ratio(None) == "—"


def test_cell_formatters_leave_the_sorted_frame_untouched() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "Avg Upside %": [18.4, -12.0, None],
            "Current Ratio": [0.82, 1.4, None],
            "Insider Ownership %": [3.9, 1.2, None],
        }
    )
    original = frame.copy(deep=True)

    display = app._format_display_frame(frame)

    pd.testing.assert_frame_equal(frame, original)
    assert display["Avg Upside %"].tolist() == ["🟢 +18.4%", "🔴 -12.0%", "—"]
    assert display["Current Ratio"].tolist() == ["🔴 0.82", "1.40", "—"]
    assert display["Insider Ownership %"].iloc[0] == "3.90%"


def test_column_help_states_the_formulas_that_were_unclear() -> None:
    from stonks.config import COLUMN_HELP

    assert "÷" in COLUMN_HELP["current_ratio"]
    assert "below 1" in COLUMN_HELP["current_ratio"]
    assert "÷" in COLUMN_HELP["fcf_margin_pct"]
    assert "capped at 150%" in COLUMN_HELP["valuation_upside_capped_pct"]
    assert "Strong Consensus" in COLUMN_HELP["valuation_triangulation"]
