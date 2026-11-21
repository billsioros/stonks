"""Tests for the detail payload parsers, against recorded NVDA payloads."""

import json
from pathlib import Path
from typing import Any

from stonks.detail import resolve_payload
import pytest

from stonks.detail_parse import (
    parse_forecast,
    parse_overview,
    parse_statistics,
)

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


# ── Statistics ───────────────────────────────────────────────────────


def test_parse_statistics_order_and_shape() -> None:
    sections = parse_statistics(_load("nvda_statistics"))
    assert [s["key"] for s in sections][:3] == ["valuation", "dates", "shares"]
    assert sections[0]["title"] == "Valuation"
    assert sections[0]["items"][0] == {
        "id": "marketcap",
        "title": "Market Cap",
        "value": "3.03T",
        "hover": "3,031,172,910,000",
    }


def test_parse_statistics_covers_every_present_section() -> None:
    keys = {s["key"] for s in parse_statistics(_load("nvda_statistics"))}
    assert {
        "valuation",
        "ratios",
        "evRatios",
        "financialPosition",
        "margins",
        "dividends",
        "shortSelling",
        "scores",
        "fairValue",
    } <= keys


def test_parse_statistics_empty_payload() -> None:
    assert parse_statistics({}) == []
    assert parse_statistics({"valuation": {"data": []}}) == []


# ── Forecast ─────────────────────────────────────────────────────────


def test_parse_forecast_targets() -> None:
    out = parse_forecast(_load("nvda_forecast"))
    assert out["targets"] == {
        "low": 130,
        "median": 230,
        "average": 240.51,
        "high": 425,
        "count": 41,
        "updated": "2026-11-19",
    }


def test_parse_forecast_estimates_and_ratings_summary() -> None:
    out = parse_forecast(_load("nvda_forecast"))
    assert out["estimates"]["annual"]["epsThis"]["growth"] == pytest.approx(
        102.70964360587004
    )
    assert out["current_ratings"]["consensus"] == "Buy"
    assert out["current_ratings"]["count"] == 63


def test_parse_forecast_analyst_actions() -> None:
    action = parse_forecast(_load("nvda_forecast"))["ratings"][0]
    assert action["firm"] == "Wedbush"
    assert action["action"] == "Reiterates"
    assert action["target_now"] == 293 and action["target_old"] == 275
    assert action["rating_new"] == "Buy"


def test_parse_forecast_empty_payload() -> None:
    out = parse_forecast({})
    assert out["targets"] is None
    assert out["current_ratings"] is None
    assert out["ratings"] == [] and out["recommendations"] == []
    assert out["estimates"] == {"annual": {}, "quarterly": {}}
