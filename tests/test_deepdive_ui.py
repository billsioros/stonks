"""AppTest coverage for the deterministic deep-dive panels."""

from __future__ import annotations

import pytest
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
            Check(
                "filings.freshness",
                "Freshness",
                "pass",
                "10-K filed 2026-02-15 (281d old)",
                "10-K <= 400 days",
                "companyfacts",
            ),
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

REAL_APP = """
from stonks.dossier import FilingEvidence, build_dossier
from stonks.deepdive_view import render_deep_dive

facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
    {"end": "2025-09-27", "filed": "2025-10-30", "form": "10-K",
     "accn": "000-2025-01", "val": 1000000000}
]}}}}}
evidence = FilingEvidence(
    cik="0000320193",
    facts=facts,
    hits=({"phrase": "material weakness", "count": 1,
           "filing_date": "2025-10-30", "accession": "000-2025-02",
           "url": "https://www.sec.gov/Archives/x"},),
    latest_10k="2025-10-30",
)
dossier = build_dossier(
    "NVDA",
    row={"revenue": 1100000000.0},
    filing_evidence=evidence,
    today="2026-11-23",
)
render_deep_dive(None, "NVDA", dossier)
"""

USER_AGENT_APP = """
from stonks.dossier import FilingEvidence, build_dossier
from stonks.deepdive_view import render_deep_dive

dossier = build_dossier(
    "NVDA",
    filing_evidence=FilingEvidence(reason="EDGAR_USER_AGENT not configured"),
)
render_deep_dive(None, "NVDA", dossier)
"""

UA_BUILDER_APP = """
from stonks import filing_evidence
from stonks.dossier import build_dossier
from stonks.deepdive_view import render_deep_dive

class NoCacheStore:
    def cache_get(self, *args, **kwargs):
        raise AssertionError("cache read before user-agent validation")

evidence = filing_evidence.build_filing_evidence("NVDA", store=NoCacheStore())
dossier = build_dossier("NVDA", filing_evidence=evidence)
render_deep_dive(None, "NVDA", dossier)
"""


def _run(app: str = APP) -> AppTest:
    at = AppTest.from_string(app, default_timeout=180)
    at.run()
    assert not at.exception, at.exception
    return at


def _values(app: str = APP) -> list[str]:
    return [str(block.value) for block in _run(app).markdown]


def test_gate_strip_has_one_badge_per_gate_with_the_right_glyph() -> None:
    values = _values()
    assert any("✅ Quality" in value for value in values)
    assert any("⛔ Filings" in value for value in values)
    assert any("❔ Forward" in value for value in values)
    assert any("➖ Portfolio fit" in value for value in values)
    assert any("50%" in value for value in values)


def test_decision_summary_card_names_unknowns_coverage_and_freshness() -> None:
    values = _values()

    assert any("### What would change my mind" in value for value in values)
    assert any("Evidence coverage: 50%" in value for value in values)
    assert any("10-K filed 2026-02-15" in value for value in values)
    assert any("forward.growth" in value for value in values)
    assert any("filings.revenue" in value for value in values)


def test_failing_checks_come_first_in_their_table() -> None:
    values = _values()
    tables = [
        value
        for value in values
        if "filings.revenue" in value and "| id | check |" in value
    ]
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


def test_gate_strip_shows_real_filings_gate_and_conflicts() -> None:
    values = _values(REAL_APP)

    assert any("⛔ Filings & guidance" in value for value in values)
    filing_list = next(
        value for value in values if value.startswith("### Read these filings")
    )
    assert "filings.revenue" in filing_list
    assert "1,100,000,000" in filing_list
    assert "000-2025-01" in filing_list
    assert "material weakness" in filing_list
    assert "https://www.sec.gov/Archives/x" in filing_list


def test_missing_user_agent_hint() -> None:
    captions = [str(c.value) for c in _run(USER_AGENT_APP).caption]
    assert captions.count("Set EDGAR_USER_AGENT to verify filings") == 1
    plain = [str(c.value) for c in _run().caption]
    assert not [value for value in plain if "Set EDGAR_USER_AGENT" in value]


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "stonks/1.0 (a@example.com)\r\nX-Evil: yes",
        "x" * 201,
        "not-an-address",
    ],
)
def test_every_user_agent_problem_shows_exactly_one_hint(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    else:
        monkeypatch.setenv("EDGAR_USER_AGENT", value)

    at = _run(UA_BUILDER_APP)
    captions = [str(caption.value) for caption in at.caption]
    tables = [str(block.value) for block in at.markdown]

    assert captions.count("Set EDGAR_USER_AGENT to verify filings") == 1
    assert sum("Set EDGAR_USER_AGENT" in caption for caption in captions) == 1
    assert any("EDGAR_USER_AGENT not configured" in table for table in tables)
