"""AppTest coverage for the deterministic deep-dive panels."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

APP = """
from stonks.dossier import Check, Dossier, Gate
from stonks.deepdive_view import render_deep_dive

dossier = Dossier(
    symbol="NVDA",
    as_of="2026-11-23T09:00:00Z",
    gates=(
        Gate("quality", "Quality", (
            Check("quality.roic", "ROIC", "pass", "14.2%", ">= 10%", "row"),
            Check("quality.cash", "Cash", "pass", "0.9", ">= 0.8", "row"),
        ), "Checks passed"),
        Gate("filings", "Filings", (
            Check("filings.cik", "CIK", "pass", "320193", "resolved", "map"),
            Check("filings.revenue", "Revenue", "fail", "1.0 vs 1.2", "<= 1%", "acc 123"),
        ), "Revenue differs"),
        Gate("forward", "Forward", (
            Check("forward.growth", "Growth", "unverified", "n/a", "> 0", "no forecast"),
        ), "No forecast"),
        Gate("fit", "Portfolio fit", (
            Check("fit.sector", "Sector", "not_applicable", "n/a", "<= 25%", "no portfolio"),
        ), "No portfolio"),
    ),
    conflicts=("revenue differs: 1.0 vs 1.2 (0000320193-25-000001)",),
    red_flags=("material weakness (2025-10-30) https://www.sec.gov/Archives/x",),
    provenance=(("screener", "row snapshot", "1h"),),
    coverage=0.5,
)
render_deep_dive(None, "NVDA", dossier)
"""


def _values() -> list[str]:
    at = AppTest.from_string(APP, default_timeout=180)
    at.run()
    assert not at.exception, at.exception
    return [str(block.value) for block in at.markdown]


def test_gate_strip_has_one_badge_per_gate_with_the_right_glyph() -> None:
    values = _values()
    assert any("✅ Quality" in value for value in values)
    assert any("⛔ Filings" in value for value in values)
    assert any("❔ Forward" in value for value in values)
    assert any("➖ Portfolio fit" in value for value in values)
    assert any("50%" in value for value in values)


def test_failing_checks_come_first_in_their_table() -> None:
    values = _values()
    tables = [value for value in values if "filings.revenue" in value]
    assert tables
    table = tables[0]
    assert table.index("filings.revenue") < table.index("filings.cik")


def test_filing_hits_render_as_dated_links() -> None:
    values = _values()
    assert any(
        "material weakness" in value
        and "2025-10-30" in value
        and "https://www.sec.gov/Archives/x" in value
        for value in values
    )


def test_not_applicable_gate_is_a_dash_not_a_green_pass() -> None:
    values = _values()
    assert any("➖ Portfolio fit" in value for value in values)
    strip = next(value for value in values if "✅ Quality" in value)
    assert "✅ Portfolio fit" not in strip
