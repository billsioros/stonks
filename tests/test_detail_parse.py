"""Tests for the detail payload parsers, against recorded NVDA payloads."""

import json
from pathlib import Path
from typing import Any

from stonks.detail import resolve_payload
from stonks.detail_parse import parse_overview

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> Any:
    return resolve_payload(json.loads((FIXTURES / f"{name}.json").read_text()))


# ── Overview ─────────────────────────────────────────────────────────


def test_parse_overview_fields() -> None:
    out = parse_overview(_load("nvda_overview"))
    assert out["market_cap"] == "3.03T"
    assert out["analyst_rating"] == "Buy"
    assert out["analyst_target"] == "244.18 (+94.52%)"
    assert out["summary"].startswith("NVIDIA Corporation operates")


def test_parse_overview_info_rows_become_absolute_urls() -> None:
    out = parse_overview(_load("nvda_overview"))
    assert out["info"][0] == {
        "label": "Industry",
        "value": "Semiconductors",
        "url": "https://stockanalysis.com/stocks/industry/semiconductors",
    }


def test_parse_overview_news_items() -> None:
    news = parse_overview(_load("nvda_overview"))["news"]
    assert 1 <= len(news) <= 10
    assert set(news[0]) == {"title", "url", "source", "ago", "summary"}
    assert news[0]["url"].startswith("https://")


def test_parse_overview_missing_fields_are_none() -> None:
    out = parse_overview({})
    assert out["market_cap"] is None and out["news"] == [] and out["info"] == []
