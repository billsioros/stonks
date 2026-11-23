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


def test_format_filter_tags_closes_strong_tags_safely() -> None:
    parts = ["**P/E**: ≥ 10, ≤ 25", "**Symbol**: ∈ ['AAPL', '<script>']"]
    html_output = app._format_filter_tags(parts)
    assert "<strong>P/E</strong>" in html_output
    assert "<script>" not in html_output  # Safely escaped
    assert "&lt;script&gt;" in html_output
    assert html_output.count("<strong>") == html_output.count("</strong>")


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


def test_cyclical_risk_flag_renders_a_badge() -> None:
    assert app._fmt_cyclical_risk(1) == "⚠️ Peak"
    assert app._fmt_cyclical_risk(0) == ""
    assert app._fmt_cyclical_risk(None) == "—"
