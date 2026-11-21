"""Tests for the detail page view helpers."""

import json
from pathlib import Path
from typing import Any

import pytest

from stonks.detail import resolve_payload
from stonks.detail_parse import parse_statement, parse_statistics
from stonks.detail_view import (
    format_cell,
    format_compact,
    format_pct,
    metrics_sections,
    range_position,
    sparkline_svg,
    statement_frame,
    yoy_pct,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> Any:
    return resolve_payload(json.loads((FIXTURES / f"{name}.json").read_text()))


# ── Formatting ───────────────────────────────────────────────────────


def test_format_compact_scales_large_numbers() -> None:
    assert format_compact(361_808_000_000) == "361.81B"
    assert format_compact(2_500_000) == "2.50M"
    assert format_compact(12_400) == "12.40K"
    assert format_compact(3.33) == "3.33"


def test_format_cell_handles_missing_and_pro() -> None:
    assert format_cell(None) == "—"
    assert format_cell("[PRO]") == "—"
    assert format_cell("") == "—"
    assert format_cell("S&P Global") == "S&P Global"


def test_range_position() -> None:
    assert range_position(100, 50, 150) == pytest.approx(0.5)
    assert range_position(None, 50, 150) is None
    assert range_position(100, 150, 50) is None


def test_yoy_pct() -> None:
    assert yoy_pct(110, 100) == pytest.approx(10.0)
    assert yoy_pct(100, 0) is None
    assert yoy_pct(None, 100) is None


# ── Statement frame ──────────────────────────────────────────────────


def test_statement_frame_columns_and_cells() -> None:
    st = parse_statement(_load("nvda_income_annual"))
    labels, rows = statement_frame(st, show_growth=False)
    assert labels[0] == "" and labels[1] == "TTM" and labels[2] == "FY2026"
    assert rows[0][0] == "Operating Revenue"
    assert len(rows[0]) == len(labels)


def test_statement_frame_growth_column() -> None:
    st = {
        "periods": [
            {"key": "2026-01-25", "label": "FY2026", "is_ttm": False},
            {"key": "2025-01-26", "label": "FY2025", "is_ttm": False},
        ],
        "rows": [
            {"id": "revenue", "label": "Revenue", "values": [110.0, 100.0]},
            {"id": "gp", "label": "Gross Profit", "values": [None, 100.0]},
        ],
    }
    labels, rows = statement_frame(st, show_growth=True)
    assert labels[-1] == "YoY"
    assert rows[0][-1] == "+10.00%"
    assert rows[1][-1] == "—"


# ── Metrics selection ────────────────────────────────────────────────


def test_metrics_sections_selects_ratio_groups() -> None:
    sections = parse_statistics(_load("nvda_statistics"))
    keys = [s["key"] for s in metrics_sections(sections)]
    assert keys == ["ratios", "evRatios", "margins", "shares"]


def test_metrics_sections_tolerates_missing_groups() -> None:
    assert (
        metrics_sections(
            [{"key": "valuation", "title": "Valuation", "text": "", "items": []}]
        )
        == []
    )


def test_format_pct_carries_its_suffix() -> None:
    assert format_pct(94.5) == "+94.50%"
    assert format_pct(-12.345) == "-12.35%"
    assert format_pct(4.0, signed=False) == "4.00%"
    assert format_pct(None) == "—"
    assert format_pct(True) == "—"
    assert format_pct("n/a") == "—"


def test_detail_overview_renders_the_card_layout() -> None:
    from streamlit.testing.v1 import AppTest

    from stonks.detail import cache_key
    from stonks.store import SQLiteStore

    store = SQLiteStore()
    key = cache_key("NVDA", "overview")
    payload = resolve_payload(json.loads((FIXTURES / "nvda_overview.json").read_text()))
    store.cache_set(key, {"data": payload, "fetched_at": 1.0}, ttl_seconds=3600)
    history_key = "hist:NVDA:1Y"
    store.cache_set(
        history_key,
        [
            {"date": "2025-11-21", "close": 100.0},
            {"date": "2026-06-01", "close": 90.0},
            {"date": "2026-11-20", "close": 125.0},
        ],
        ttl_seconds=3600,
    )
    try:
        at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
        at.session_state["page"] = "detail"
        at.session_state["detail_symbol"] = "NVDA"
        at.run()
        assert not at.exception
        rendered = " ".join(str(el.proto.body) for el in at.get("html"))
        assert 'class="sk-page-ticker"' in rendered
        assert 'class="sk-symbol"' in rendered
        assert 'class="sk-range-track"' in rendered
        assert 'class="sk-pills"' in rendered
        assert 'class="sk-grid"' in rendered
        assert 'class="sk-chart"' in rendered
        assert "sk-spark" in rendered
        assert 'class="sk-news-item"' in rendered
    finally:
        store.cache_delete(key)
        store.cache_delete(history_key)


def test_sparkline_svg_draws_a_line_and_area() -> None:
    svg = sparkline_svg([100.0, 90.0, 110.0])
    assert svg.startswith("<svg")
    assert svg.count("polyline") == 1
    assert "<polygon" in svg


def test_sparkline_svg_needs_two_points() -> None:
    assert sparkline_svg([]) == ""
    assert sparkline_svg([5.0]) == ""


def test_forecast_without_coverage_says_so_once() -> None:
    from streamlit.testing.v1 import AppTest

    from stonks.detail import cache_key
    from stonks.store import SQLiteStore

    store = SQLiteStore()
    keys = [cache_key("NVDA", "overview"), cache_key("NVDA", "forecast")]
    store.cache_set(
        keys[0],
        {
            "data": resolve_payload(
                json.loads((FIXTURES / "nvda_overview.json").read_text())
            ),
            "fetched_at": 1.0,
        },
        ttl_seconds=3600,
    )
    store.cache_set(keys[1], {"data": {}, "fetched_at": 1.0}, ttl_seconds=3600)
    try:
        at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
        at.session_state["page"] = "detail"
        at.session_state["detail_symbol"] = "NVDA"
        at.session_state["detail_section_NVDA"] = "Forecast"
        at.run()
        assert not at.exception
        assert [str(item.value) for item in at.info] == [
            "StockAnalysis has no analyst coverage for NVDA."
        ]
    finally:
        for key in keys:
            store.cache_delete(key)


def test_chart_range_switch_reads_the_selected_span() -> None:
    from streamlit.testing.v1 import AppTest

    from stonks.detail import cache_key
    from stonks.store import SQLiteStore

    store = SQLiteStore()
    keys = [cache_key("NVDA", "overview"), "hist:NVDA:1Y"]
    store.cache_set(
        keys[0],
        {
            "data": resolve_payload(
                json.loads((FIXTURES / "nvda_overview.json").read_text())
            ),
            "fetched_at": 1.0,
        },
        ttl_seconds=3600,
    )
    store.cache_set(
        keys[1],
        [{"date": f"2026-01-{day:02d}", "close": 100.0 + day} for day in range(1, 31)],
        ttl_seconds=3600,
    )
    try:
        at = AppTest.from_file("src/stonks/app.py", default_timeout=180)
        at.session_state["page"] = "detail"
        at.session_state["detail_symbol"] = "NVDA"
        at.session_state["detail_chart_span_NVDA"] = "1M"
        at.run()
        assert not at.exception
        rendered = " ".join(str(el.proto.body) for el in at.get("html"))
        # 1M is the last 21 sessions of the year, so January's first days drop out.
        assert "2026-01-30" in rendered
        assert "2026-01-10" in rendered
        assert "2026-01-01" not in rendered
    finally:
        for key in keys:
            store.cache_delete(key)
