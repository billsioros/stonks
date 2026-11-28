import pytest

from stonks.report import (
    ADVISOR_HEADINGS,
    AdvisorPick,
    AdvisorReport,
    parse_advisor_reply,
)


def _reply(summary: str, picks: list[dict]) -> str:
    import json

    return json.dumps({"summary": summary, "picks": picks})


def _summary() -> str:
    return "\n\n".join(
        f"## {heading}\nText [Source: AAA, pe_ratio]" for heading in ADVISOR_HEADINGS
    )


def test_parse_advisor_reply_accepts_fenced_json():
    text = (
        "```json\n"
        + _reply(_summary(), [{"symbol": "aaa", "weight": 12.5, "reason": "Growth"}])
        + "\n```"
    )
    parsed = parse_advisor_reply(text, {"AAA"})
    assert parsed == AdvisorReport(
        summary=_summary(),
        picks=(AdvisorPick("AAA", 12.5, "Growth"),),
    )


def test_parse_advisor_reply_drops_unknown_and_duplicate_symbols():
    text = _reply(
        _summary(),
        [
            {"symbol": "AAA", "weight": 10, "reason": "first"},
            {"symbol": "AAA", "weight": 8, "reason": "duplicate"},
            {"symbol": "ZZZ", "weight": 5, "reason": "not in pool"},
        ],
    )
    parsed = parse_advisor_reply(text, {"AAA", "BBB"})
    assert parsed.picks == (AdvisorPick("AAA", 10.0, "first"),)


def test_parse_advisor_reply_rejects_missing_heading():
    text = _reply(
        "## Summary\nOnly one heading",
        [{"symbol": "AAA", "weight": 10, "reason": "ok"}],
    )
    with pytest.raises(ValueError, match="headings"):
        parse_advisor_reply(text, {"AAA"})


def test_parse_advisor_reply_rejects_bad_weight():
    text = _reply(_summary(), [{"symbol": "AAA", "weight": -1, "reason": "bad"}])
    with pytest.raises(ValueError, match="weight"):
        parse_advisor_reply(text, {"AAA"})


def test_parse_advisor_reply_rejects_empty_picks():
    text = _reply(_summary(), [{"symbol": "ZZZ", "weight": 10, "reason": "unknown"}])
    with pytest.raises(ValueError, match="no valid picks"):
        parse_advisor_reply(text, {"AAA"})
