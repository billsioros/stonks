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
    metrics_sections,
    range_position,
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
