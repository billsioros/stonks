"""Prompt construction and the opt-in OpenRouter screener report.

The prompt builder turns the filtered screener universe into prompt text: no
network call and no Streamlit, so the payload is testable without a runtime.
It carries aggregate figures and ticker symbols only -- never a company
description -- so no row-level prose leaves the machine.
`request_report` is the one network call, made only when the user opts in;
`app.py` owns the widgets.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from openrouter import OpenRouter, errors
from openrouter.components import ChatSystemMessageTypedDict, ChatUserMessageTypedDict

from stonks.config import COLUMN_DISPLAY_NAMES

__all__ = [
    "REPORT_MODEL",
    "SYSTEM_INSTRUCTION",
    "explain_error",
    "request_report",
    "screener_report_prompt",
]

REPORT_MODEL: str = "openrouter/free"

SYSTEM_INSTRUCTION: str = (
    "You are a stock-screening assistant. Be concise and informative: short, "
    "scannable markdown with no filler. Use only the figures provided -- do not "
    "invent data or make price predictions. This is research support, not "
    "financial advice."
)

# The report skeleton, held to the same shape as the roomies report so the two
# read alike; the data follows the final "Data:" line.
REPORT_SECTIONS: str = (
    "Write a stock-screener report as markdown with exactly these sections, in this order:\n"
    "\n"
    "## Summary\n"
    "One or two sentences: the character of this filtered universe, and whether "
    "its valuation and growth figures point to a coherent theme or a mixed bag.\n"
    "\n"
    "## Key numbers\n"
    "The most telling figures, as a short bullet list (e.g., stocks matching, "
    "median valuation, largest upside, industry concentration).\n"
    "\n"
    "## Observations\n"
    "What stands out in the screened set, one bullet per point, each backed by "
    "an exact figure from the data below. Separate broad patterns from a single "
    "symbol's outlier reading.\n"
    "\n"
    "## What to look at\n"
    "4 to 6 concrete follow-ups, ordered by how much the figures support them: "
    "name the exact symbols and figures that warrant a closer look, and say what "
    "would confirm or rule each out. Do not recommend trades.\n"
    "\n"
    "## TL;DR\n"
    "Three or four short, plain sentences condensing the report: the most telling "
    "figures and the 1-2 names worth researching further -- every claim backed by "
    "figures from the data. No recap of above headings.\n"
    "\n"
    "Data:\n"
)

# The leaderboards shown below: prompt title, row key, column label.
_LEADERBOARDS: tuple[tuple[str, str, str], ...] = (
    ("Largest analyst price-target upside", "pt_upside_pct", "PT upside"),
    ("Largest DCF upside", "dcf_upside_pct", "DCF upside"),
    ("Highest dividend yield", "dividend_yield_pct", "Div yield"),
    ("Fastest 5-year revenue growth", "revenue_growth_5y_pct", "Rev growth 5Y"),
)
_LEADER_LIMIT = 5

# Every screener field goes into the prompt. Company prose stays local; tickers
# appear in the leaderboards instead of a row dump.
_OMITTED_COLUMNS = frozenset({"symbol", "description"})
_CATEGORICAL_COLUMNS = frozenset(
    {"exchange", "type", "mic", "currency", "industry", "rating"}
)


def _number(value: Any) -> float | None:
    """A finite number, or None for a missing/blank/non-numeric cell."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _num(value: Any) -> str:
    """A two-decimal figure, or a dash when there is nothing to average."""
    number = _number(value)
    return "n/a" if number is None else f"{number:.2f}"


def _pct(value: Any) -> str:
    """A signed percentage, or a dash when the figure is absent."""
    number = _number(value)
    return "n/a" if number is None else f"{number:+.1f}%"


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """A markdown table with escaped pipes so a cell cannot break the table."""
    head = "| " + " | ".join(headers) + " |"
    rule = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |"
        for row in rows
    ]
    return "\n".join([head, rule, *body])


def _median(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [number for row in rows if (number := _number(row.get(key))) is not None]
    return statistics.median(values) if values else None


def _filter_text(filters: Mapping[str, Any] | None) -> str:
    """The active filters as plain bounds, or a dash when none are set."""
    if not filters:
        return "- (none)"
    parts: list[str] = []
    for column, spec in filters.items():
        if not isinstance(spec, Mapping):
            continue
        bounds: list[str] = []
        if spec.get("min") is not None:
            bounds.append(f">= {spec['min']}")
        if spec.get("max") is not None:
            bounds.append(f"<= {spec['max']}")
        if spec.get("values"):
            bounds.append("in " + ", ".join(str(value) for value in spec["values"]))
        if bounds:
            parts.append(f"{column} " + " ".join(bounds))
    return "; ".join(parts) if parts else "- (none)"


def _leaderboard(rows: Sequence[Mapping[str, Any]], key: str, label: str) -> str:
    """The highest values of one metric, with ticker labels and no other prose."""
    scored: list[tuple[str, float]] = []
    for row in rows:
        symbol = row.get("symbol")
        value = _number(row.get(key))
        if symbol and value is not None:
            scored.append((str(symbol), value))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    if not scored:
        return "- (none)"
    return _md_table(
        ["Symbol", label],
        [(symbol, _pct(value)) for symbol, value in scored[:_LEADER_LIMIT]],
    )


def _screener_columns() -> list[tuple[str, str]]:
    """The screener fields and their UI labels, minus symbol and company prose."""
    return [
        (key, label)
        for key, label in COLUMN_DISPLAY_NAMES.items()
        if key not in _OMITTED_COLUMNS
    ]


def _numeric_summary(
    rows: Sequence[Mapping[str, Any]], key: str, label: str
) -> tuple[str, str, str, str, str]:
    """Median, range and coverage for one numeric screener field."""
    values = [number for row in rows if (number := _number(row.get(key))) is not None]
    if not values:
        return (label, "n/a", "n/a", "n/a", "0")
    return (
        label,
        f"{statistics.median(values):.2f}",
        f"{min(values):.2f}",
        f"{max(values):.2f}",
        str(len(values)),
    )


def _category_summary(rows: Sequence[Mapping[str, Any]], key: str, label: str) -> str:
    """How many stocks hold each value of a categorical screener field."""
    counts = Counter(str(row[key]) for row in rows if row.get(key) not in (None, ""))
    if not counts:
        return f"{label} (stocks per value):\n- (none)"
    return f"{label} (stocks per value):\n" + _md_table(
        [label, "Stocks"],
        [(value, str(count)) for value, count in counts.most_common()],
    )


def screener_report_prompt(
    rows: Sequence[Mapping[str, Any]],
    total_matching: int,
    filters: Mapping[str, Any] | None = None,
    search_query: str = "",
    view_preset: str = "",
) -> str:
    """The filtered screener universe as a prompt of markdown tables.

    `rows` holds every stock matching the current filters and search, so the
    report cannot drift from the universe behind the table. Empty and
    non-numeric cells are skipped rather than dividing or crashing. Only ticker
    symbols and aggregate figures are sent; company descriptions stay local.
    """
    hedge_fund_buys = sum(1 for row in rows if _number(row.get("hedge_fund_buys")) == 1)
    overview = _md_table(
        ["Metric", "Value"],
        [
            ("Matching stocks", str(total_matching)),
            ("Rows summarized", str(len(rows))),
            ("Filters", _filter_text(filters)),
            ("Search", f'"{search_query}"' if search_query else "- (none)"),
            ("View", view_preset or "- (none)"),
            ("Median price", _num(_median(rows, "price"))),
            ("Median P/E", _num(_median(rows, "pe_ratio"))),
            ("Median PT upside", _pct(_median(rows, "pt_upside_pct"))),
            ("Median DCF upside", _pct(_median(rows, "dcf_upside_pct"))),
            ("Hedge fund buys", str(hedge_fund_buys)),
        ],
    )

    numeric_rows: list[tuple[str, str, str, str, str]] = []
    category_sections: list[str] = []
    for key, label in _screener_columns():
        if key in _CATEGORICAL_COLUMNS:
            category_sections.append(_category_summary(rows, key, label))
        else:
            numeric_rows.append(_numeric_summary(rows, key, label))

    sections: list[str] = [
        overview,
        "All screener fields (median / min / max / stocks with data):",
        _md_table(["Metric", "Median", "Min", "Max", "With data"], numeric_rows),
        *category_sections,
    ]
    for title, key, label in _LEADERBOARDS:
        sections.extend([f"{title} (highest first):", _leaderboard(rows, key, label)])
    return REPORT_SECTIONS + "\n".join(sections)


def request_report(
    prompt: str,
    *,
    api_key: str,
    model: str = REPORT_MODEL,
    client: OpenRouter | None = None,
) -> str:
    """Send `prompt` to OpenRouter and return the reply text, or "" when absent.

    The only network call in the module, and only made when the user opts in.
    An injected `client` is used as-is and never closed; with no `client` one is
    built from `api_key`. Errors are not caught -- the caller decides how to
    surface them.
    """
    messages: list[ChatSystemMessageTypedDict | ChatUserMessageTypedDict] = [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": prompt},
    ]
    owned = client if client is not None else OpenRouter(api_key=api_key)
    result = owned.chat.send(
        messages=messages,
        model=model,
        temperature=0.4,
        max_tokens=1024,
        stream=False,
    )
    if not result.choices:
        return ""
    content = result.choices[0].message.content
    if not isinstance(content, str):
        return ""
    return content


def explain_error(exc: Exception) -> str:
    """Turn an OpenRouter failure into a short, actionable message."""
    if isinstance(exc, errors.OpenRouterError):
        code = exc.status_code
        if code in (500, 502, 503, 504, 529):
            return (
                "OpenRouter is busy right now — the free models see the "
                "heaviest spikes in demand, usually temporary. Try again in "
                "a moment."
            )
        if code == 429:
            return (
                "OpenRouter's rate limit was reached. Free models have the "
                "tightest limits; try again in a moment."
            )
        if code == 401:
            return "OpenRouter rejected the API key. Check OPENROUTER_API_KEY."
        if code == 403:
            return (
                "OpenRouter says this API key lacks permission. Check "
                "OPENROUTER_API_KEY."
            )
        if code in (400, 402, 404):
            return (
                "OpenRouter could not serve this request with the configured "
                "model. Check OPENROUTER_MODEL."
            )
        return f"OpenRouter returned HTTP {code}."
    if isinstance(exc, httpx.HTTPError):
        return (
            "Could not reach OpenRouter — check the network connection and try again."
        )
    return "Could not reach OpenRouter — check the network connection and try again."
