"""Prompt construction and the opt-in OpenRouter reports.

The screener builder turns the filtered universe into aggregate prompt text;
the symbol builder turns one ticker's screener row and StockAnalysis pages into
a decision memo. Both are pure: no network call and no Streamlit, so payloads
are testable without a runtime. `request_report` is the one network call, made
only when the user opts in; `report_view.py` owns the widgets.
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
from stonks.dossier import Check, Dossier, gate_status

__all__ = [
    "REPORT_MODEL",
    "SYMBOL_MAX_TOKENS",
    "SYMBOL_SYSTEM_INSTRUCTION",
    "SYSTEM_INSTRUCTION",
    "dossier_block",
    "explain_error",
    "request_report",
    "screener_report_prompt",
    "symbol_report_prompt",
]

REPORT_MODEL: str = "openrouter/free"
SYMBOL_MAX_TOKENS = 4000
UNVERIFIED_HEADING = "## What this dossier could not verify"

SYSTEM_INSTRUCTION: str = (
    "You are a stock-screening assistant. Be concise and informative: short, "
    "scannable markdown with no filler. Use only the figures provided -- do not "
    "invent data or make price predictions. Cite every figure with its source "
    "row and field from the data below. This is research support, not "
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
    "Context: hedge_fund_buys (13F Whale) marks stocks in HedgeFollow's latest "
    "largest 13F buys. Filings lag up to 45 days and a crowded position is not "
    "a signal by itself; do not penalize a stock because hedge_fund_buys is 0.\n"
    "\n"
    "Citations: inline every figure or claim with the source row and field it "
    "came from, e.g. `[Source: AAPL, pe_ratio]` or `[Source: Overview, Median "
    "P/E]`. A section heading is not a source.\n"
    "\n"
    "Data:\n"
)

SYMBOL_SYSTEM_INSTRUCTION: str = (
    "You are a fundamental investment analyst writing a decision memo about one "
    "stock. Use only the figures and text provided. Quantify every claim, keep "
    "facts separate from interpretation, and treat missing fields as unavailable "
    "rather than guessing. Today's price is the decision price: judge valuation "
    "against it. Cite the check id behind every dossier claim. For filing facts, "
    "cite the accession number and filing date too, e.g. `[Source: "
    "filings.material_weakness, 0000320193-26-000001, 2026-02-01]`. Never assert "
    "a moat, catalyst or filing fact that is absent from the dossier. Cite moat-proxy "
    "quality check IDs (quality.*) and state explicitly when a moat is not proven "
    "by the evidence. Treat an "
    "unverified check as unknown, never as favourable evidence, and keep trailing "
    "results separate from forward estimates. Name the dossier's check coverage "
    "and the single most important unknown in the TL;DR. If the filings gate "
    "fails, lead the memo with that failure rather than the valuation case. "
    "This is research support, not financial advice."
)

# A decision memo, not a screener summary: the verdict is about buying at the
# price shown in the data, and the risk section is deliberately prominent.
SYMBOL_REPORT_SECTIONS: str = (
    "Write an investment decision memo as markdown with exactly these sections, "
    "in this order:\n"
    "\n"
    "## Business and moat\n"
    "What the company does, its industry, and the durable advantages or "
    "weaknesses the data actually supports. Cite moat-proxy quality check IDs "
    "(quality.*) and state explicitly when a moat is not proven by the evidence.\n"
    "\n"
    "## Growth and profitability\n"
    "Revenue and earnings trends, margins, returns on capital, and whether "
    "growth is translating into profit. Cite exact figures.\n"
    "\n"
    "## Cash flow and balance sheet\n"
    "Cash generation, capital spending, liquidity, debt and coverage. Separate "
    "accounting profit from cash the business actually keeps.\n"
    "\n"
    "## Valuation at today's price\n"
    "Judge today's price against earnings, cash flow, the supplied fair values "
    "and analyst targets. Say explicitly what is already priced in.\n"
    "\n"
    "## Risks\n"
    "The strongest case against buying now. Lead with the two or three biggest "
    "threats, quantify each with figures from the data, and include leverage, "
    "coverage, short interest, valuation, dividend durability and the supplied "
    "risk scores where present. Do not soften them.\n"
    "\n"
    "## What would change the answer\n"
    "Concrete figures or events that would flip the verdict either way.\n"
    "\n"
    "## TL;DR\n"
    "Start with a single word, YES or NO, meaning whether to buy at today's "
    "price. Follow with two to four short sentences naming the deciding figures, "
    "the main risk, the dossier's check coverage and the single most important "
    "unknown. No hedging, and no recap of the headings above.\n"
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

# Every screener field goes into the prompt. The ticker is the key of every
# table instead of a metric of its own; every other column is summarised, and
# the provider's description is carried in the company profile block.
_OMITTED_COLUMNS = frozenset({"symbol"})
_DESCRIPTION_LIMIT = 240
_PROFILE_LIMIT = 60
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


def _profile_block(rows: Sequence[Mapping[str, Any]]) -> str:
    """One line per stock: ticker, company name and description.

    Descriptions are vendor prose, so they are truncated rather than trusted to
    fit a token budget; the remainder of a long universe is named, not dropped
    silently.
    """
    shown = rows[:_PROFILE_LIMIT]
    table = _md_table(
        ["Symbol", "Company"],
        [
            (
                str(row.get("symbol") or "-"),
                str(row.get("description") or "-")[:_DESCRIPTION_LIMIT] or "- (none)",
            )
            for row in shown
        ],
    )
    if len(rows) > len(shown):
        return f"{table}\n(First {len(shown)} of {len(rows)} companies.)"
    return table


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
    non-numeric cells are skipped rather than dividing or crashing. Every
    screener field supplied on the rows reaches the prompt: aggregates for the
    numeric columns, value counts for the categorical ones, and one profile
    line per company.
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
        "Company profiles:\n" + _profile_block(rows),
        "All screener fields (median / min / max / stocks with data):",
        _md_table(["Metric", "Median", "Min", "Max", "With data"], numeric_rows),
        *category_sections,
    ]
    for title, key, label in _LEADERBOARDS:
        sections.extend([f"{title} (highest first):", _leaderboard(rows, key, label)])
    return REPORT_SECTIONS + "\n".join(sections)


_STATEMENT_LABELS: dict[str, str] = {
    "income-statement": "Income statement",
    "balance-sheet": "Balance sheet",
    "cash-flow-statement": "Cash flow statement",
    "ratios": "Ratios",
}


def _value_text(value: Any) -> str:
    """Render a cell for the prompt, naming missing data explicitly."""
    if value is None or value == "":
        return "not available"
    if isinstance(value, str):
        return value
    number = _number(value)
    return f"{number:.2f}" if number is not None else str(value)


def _symbol_row_pairs(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Every screener field for one ticker, with today's price called out."""
    pairs: list[tuple[str, str]] = []
    for key, label in COLUMN_DISPLAY_NAMES.items():
        if key == "price":
            label = "Price today"
        value = row.get(key)
        text = _pct(value) if key.endswith("_pct") else _value_text(value)
        pairs.append((label, text))
    return pairs


_OVERVIEW_LABELS: tuple[tuple[str, str], ...] = (
    ("summary", "Business description"),
    ("revenue", "Revenue"),
    ("revenue_growth", "Revenue growth"),
    ("net_income", "Net income"),
    ("net_income_growth", "Net income growth"),
    ("eps", "EPS"),
    ("pe_ratio", "P/E"),
    ("forward_pe", "Forward P/E"),
    ("shares_out", "Shares outstanding"),
    ("beta", "Beta"),
    ("dividend", "Dividend"),
    ("ex_dividend_date", "Ex-dividend date"),
    ("analyst_rating", "Analyst rating"),
    ("analyst_target", "Analyst target"),
    ("earnings_date", "Earnings date"),
)


def _statistics_block(sections: Sequence[Mapping[str, Any]]) -> str:
    blocks: list[str] = []
    for section in sections:
        title = section.get("title") or section.get("key") or "Statistics"
        blocks.append(f"### {title}")
        if section.get("text"):
            blocks.append(str(section["text"]))
        items = section.get("items") or []
        if not items:
            blocks.append("not available")
            continue
        rows = [
            (
                item.get("title") or item.get("id") or "",
                _value_text(item.get("value")),
                _value_text(item.get("hover")),
            )
            for item in items
            if isinstance(item, Mapping)
        ]
        blocks.append(_md_table(["Field", "Value", "Exact"], rows))
    return "\n\n".join(blocks) if blocks else "not available"


def _statement_table(data: Mapping[str, Any]) -> str:
    all_periods = data.get("periods") or []
    periods = all_periods[
        :3
    ]  # Most recent first; keeps the prompt within model limits.
    note = (
        f"Showing the 3 most recent periods of {len(all_periods)}.\n"
        if len(all_periods) > 3
        else ""
    )
    headers = ["Metric", *[str(p.get("label") or p.get("key") or "") for p in periods]]
    rows: list[list[str]] = []
    for item in data.get("rows") or []:
        values = [_value_text(value) for value in item.get("values") or []][
            : len(periods)
        ]
        values += ["not available"] * (len(headers) - 1 - len(values))
        rows.append([str(item.get("label") or item.get("id") or ""), *values])
    return note + _md_table(headers, rows)


def _forecast_block(forecast: Mapping[str, Any] | None) -> str:
    if not forecast:
        return "not available"
    parts: list[str] = []
    targets = forecast.get("targets") or {}
    parts.append(
        "Analyst price targets:\n"
        + _md_table(
            ["Metric", "Value"],
            [
                ("Low", _value_text(targets.get("low"))),
                ("Analyst price target (median)", _value_text(targets.get("median"))),
                ("Average", _value_text(targets.get("average"))),
                ("High", _value_text(targets.get("high"))),
                ("Count", _value_text(targets.get("count"))),
                ("Updated", _value_text(targets.get("updated"))),
            ],
        )
    )
    consensus = forecast.get("current_ratings") or {}
    parts.append(
        "Analyst consensus:\n"
        + _md_table(
            ["Metric", "Value"],
            [(key, _value_text(value)) for key, value in consensus.items()],
        )
    )
    estimate_rows: list[tuple[str, str, str, str, str]] = []
    for basis, metrics in (forecast.get("estimates") or {}).items():
        for metric, values in metrics.items():
            estimate_rows.append(
                (
                    str(basis),
                    str(metric),
                    _value_text(values.get("last")),
                    _value_text(values.get("this")),
                    _pct(values.get("growth")),
                )
            )
    parts.append(
        "Analyst estimates:\n"
        + _md_table(
            ["Basis", "Metric", "Last", "This", "Growth"],
            estimate_rows or [("not available", "", "", "", "")],
        )
    )
    actions = forecast.get("ratings") or []
    parts.append(
        "Recent analyst actions:\n"
        + _md_table(
            ["Date", "Firm", "Action", "Target now", "Target before", "Rating"],
            [
                (
                    _value_text(item.get("date")),
                    _value_text(item.get("firm")),
                    _value_text(item.get("action")),
                    _value_text(item.get("target_now")),
                    _value_text(item.get("target_old")),
                    _value_text(item.get("rating_new")),
                )
                for item in actions
                if isinstance(item, Mapping)
            ]
            or [("not available", "", "", "", "", "")],
        )
    )
    return "\n\n".join(parts)


def _history_block(history: Sequence[Mapping[str, Any]]) -> str:
    if len(history) < 2:
        return "not available"
    first, last = history[0], history[-1]
    start, end = _number(first.get("close")), _number(last.get("close"))
    change = ((end / start - 1.0) * 100.0) if start and end else None
    return _md_table(
        ["Metric", "Value"],
        [
            ("First date", _value_text(first.get("date"))),
            ("First close", _num(start)),
            ("Last date", _value_text(last.get("date"))),
            ("Last close", _num(end)),
            ("Change", _pct(change)),
        ],
    )


def _news_block(news: Sequence[Mapping[str, Any]]) -> str:
    if not news:
        return "not available"
    return _md_table(
        ["Headline", "Source", "When", "Summary"],
        [
            (
                _value_text(item.get("title")),
                _value_text(item.get("source")),
                _value_text(item.get("ago")),
                _value_text(item.get("summary")),
            )
            for item in news
            if isinstance(item, Mapping)
        ],
    )


def dossier_block(dossier: Dossier) -> str:
    """A compact, table-only rendering of the deterministic verdict.

    Passing checks omit their evidence strings: the number and threshold are
    enough there, while a fail or an unverifiable check keeps the reason that a
    reader needs to audit the memo.
    """
    lines = [
        "## Verdict",
        (
            f"Symbol: {dossier.symbol} | as of {dossier.as_of} | "
            f"coverage {dossier.coverage:.0%}"
        ),
        "",
        _md_table(
            ["Gate", "Status", "Summary"],
            [
                (
                    gate.label,
                    gate_status(gate.checks),
                    gate.summary,
                )
                for gate in dossier.gates
            ],
        ),
    ]
    for gate in dossier.gates:
        lines.extend(
            [
                "",
                f"### {gate.label}",
                _md_table(
                    ["id", "check", "status", "value", "threshold", "evidence"],
                    [
                        (
                            check.id,
                            check.label,
                            check.status,
                            check.value,
                            check.threshold,
                            check.evidence if check.status != "pass" else "",
                        )
                        for check in gate.checks
                    ],
                ),
            ]
        )
    lines.extend(
        [
            "",
            f"Conflicts: {'; '.join(dossier.conflicts) if dossier.conflicts else 'none'}",
            f"Red flags: {'; '.join(dossier.red_flags) if dossier.red_flags else 'none'}",
            "Provenance:\n"
            + _md_table(
                ["Source", "What", "Age"],
                [tuple(source) for source in dossier.provenance],
            ),
        ]
    )
    return "\n".join(lines)


def _unverified_section(dossier: Dossier) -> str:
    missing = [
        check
        for gate in dossier.gates
        for check in gate.checks
        if check.status == "unverified"
    ]

    def reason(check: Check) -> str:
        value = str(check.value).strip()
        if value and value.lower() not in {"n/a", "—", "unknown"}:
            return value
        return str(check.evidence or "no reason recorded")

    body = (
        "\n".join(f"- {check.id}: {reason(check)}" for check in missing)
        if missing
        else "None: every applicable check was verified."
    )
    return (
        f"{UNVERIFIED_HEADING}\n{body}\n\n"
        "In the TL;DR, name the check coverage and the single most important "
        "unknown; do not treat any item above as a fact."
    )


def symbol_report_prompt(
    symbol: str,
    *,
    row: Mapping[str, Any] | None = None,
    overview: Mapping[str, Any] | None = None,
    statistics: Sequence[Mapping[str, Any]] | None = None,
    forecast: Mapping[str, Any] | None = None,
    statements: Mapping[str, Mapping[str, Any]] | None = None,
    history: Sequence[Mapping[str, Any]] | None = None,
    news: Sequence[Mapping[str, Any]] | None = None,
    dossier: Dossier | None = None,
) -> str:
    """One symbol's cached data as the input to an investment decision memo.

    Every supplied field is included so the verdict can be checked against the
    figures; missing provider sections are named rather than silently skipped.
    A dossier, when present, leads with the deterministic verdict and forces a
    section naming everything that could not be verified.
    """
    overview = overview or {}
    statement_blocks: list[str] = []
    for key, data in (statements or {}).items():
        if not data:  # PRO-gated or failed pages carry no rows.
            continue
        statement, _, period = key.partition(" ")
        label = _STATEMENT_LABELS.get(statement, statement)
        statement_blocks.append(f"### {label} — {period}\n" + _statement_table(data))
    sections = [
        f"Symbol: {symbol}",
        "Screener row:\n"
        + _md_table(["Metric", "Value"], _symbol_row_pairs(row or {})),
        "Overview:\n"
        + _md_table(
            ["Metric", "Value"],
            [
                (label, _value_text(overview.get(key)))
                for key, label in _OVERVIEW_LABELS
            ],
        ),
        "Statistics:\n" + _statistics_block(statistics or []),
        "Forecast:\n" + _forecast_block(forecast),
        "Financial statements:\n"
        + ("\n\n".join(statement_blocks) if statement_blocks else "not available"),
        "Price history:\n" + _history_block(history or []),
        "Recent news:\n"
        + _news_block(news if news is not None else overview.get("news") or []),
    ]
    if dossier is not None:
        sections.insert(0, dossier_block(dossier))
        skeleton = SYMBOL_REPORT_SECTIONS.replace(
            "## TL;DR\n", _unverified_section(dossier) + "\n\n## TL;DR\n"
        )
    else:
        skeleton = SYMBOL_REPORT_SECTIONS
    return skeleton + "\n\n".join(sections)


def request_report(
    prompt: str,
    *,
    api_key: str,
    model: str = REPORT_MODEL,
    client: OpenRouter | None = None,
    system_instruction: str = SYSTEM_INSTRUCTION,
    max_tokens: int = 1024,
) -> str:
    """Send `prompt` to OpenRouter and return the reply text, or "" when absent.

    The only network call in the module, and only made when the user opts in.
    An injected `client` is used as-is and never closed; with no `client` one is
    built from `api_key`. Errors are not caught -- the caller decides how to
    surface them. The symbol report overrides the instruction and token budget.
    """
    messages: list[ChatSystemMessageTypedDict | ChatUserMessageTypedDict] = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": prompt},
    ]
    owned = client if client is not None else OpenRouter(api_key=api_key)
    result = owned.chat.send(
        messages=messages,
        model=model,
        temperature=0.4,
        max_tokens=max_tokens,
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
