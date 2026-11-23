"""Streamlit widgets for the opt-in OpenRouter reports.

Both reports share one renderer; the screener passes a prompt directly, while
the symbol report builds its prompt only after the user clicks Generate so a
rerun never triggers eleven provider requests on its own.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import streamlit as st

from stonks import deepdive_view, detail, detail_parse, dossier, report
from stonks.dossier import Dossier
from stonks.store import SQLiteStore

# The dossier block is part of the prompt, so a changed filing also changes the
# cache key of `_cached_report` without a second, redundant hash argument.
SYMBOL_MAX_TOKENS = report.SYMBOL_MAX_TOKENS

__all__ = [
    "SYMBOL_MAX_TOKENS",
    "render_llm_report",
    "render_symbol_report",
    "symbol_report_prompt_for",
    "symbol_report_prompt_parts",
]

_DefaultCaption = Callable[[str], str]


@st.cache_data(show_spinner=False)
def _cached_report(
    prompt: str,
    api_key: str,
    model: str,
    system_instruction: str,
    max_tokens: int,
) -> str:
    """Cache the reply per prompt, key, model, instruction and token budget."""
    return report.request_report(
        prompt,
        api_key=api_key,
        model=model,
        system_instruction=system_instruction,
        max_tokens=max_tokens,
    )


def render_llm_report(
    *,
    scope_key: str,
    heading: str,
    prompt: str = "",
    prompt_factory: Callable[[], str] | None = None,
    caption: _DefaultCaption | None = None,
    system_instruction: str = report.SYSTEM_INSTRUCTION,
    max_tokens: int = 1024,
    before_report: Callable[[], None] | None = None,
) -> None:
    """One collapsible, opt-in report; every widget is namespaced by `scope_key`.

    `prompt_factory` defers expensive data gathering until the user opens Debug
    or clicks Generate, and its result is kept in session state so redraws and
    the later Generate click do not build it again. Network and SDK failures
    are shown, never raised.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_MODEL") or report.REPORT_MODEL
    generated = st.session_state.get(scope_key, False)
    prompt_key = f"{scope_key}-prompt"
    with st.expander(heading, expanded=bool(generated), key=f"{scope_key}-report"):
        if not api_key:
            key_col, button_col = st.columns((3, 1), vertical_alignment="bottom")
            api_key = key_col.text_input(
                "OpenRouter API key (set OPENROUTER_API_KEY to skip this field)",
                type="password",
                key=f"{scope_key}-key",
            )
            clicked = button_col.button(
                "Generate report", key=f"{scope_key}-btn", disabled=not api_key
            )
        else:
            clicked = st.button("Generate report", key=f"{scope_key}-btn")
        if caption is None:

            def caption(value: str) -> str:
                return (
                    f"Model: {value} — every screener field, including "
                    "company names and descriptions, is sent."
                )

        st.caption(caption(model))
        if api_key and (generated or clicked):
            if (
                clicked
                and prompt_factory is not None
                and not st.session_state.get(prompt_key)
            ):
                with st.spinner("Refreshing data for this symbol…"):
                    prompt = prompt_factory()
                st.session_state[prompt_key] = prompt
            else:
                prompt = prompt or str(st.session_state.get(prompt_key, ""))
            if before_report is not None:
                before_report()
            with st.spinner("Asking OpenRouter…"):
                try:
                    reply = _cached_report(
                        prompt, api_key, model, system_instruction, max_tokens
                    )
                except Exception as exc:  # noqa: BLE001 - never crash the tab on an SDK failure
                    st.error(report.explain_error(exc))
                else:
                    st.session_state[scope_key] = reply
                    with st.container(border=True):
                        st.markdown(reply)
        if st.toggle("Debug: prompt sent to OpenRouter", key=f"{scope_key}-debug"):
            shown_prompt = prompt or str(st.session_state.get(prompt_key, ""))
            if not shown_prompt and prompt_factory is not None:
                try:
                    with st.spinner("Building prompt…"):
                        shown_prompt = prompt_factory()
                except Exception as exc:  # noqa: BLE001 - keep the tab usable on fetch failure
                    st.error(f"Could not build the prompt: {exc}")
                    shown_prompt = "Prompt unavailable — see the error above."
                else:
                    st.session_state[prompt_key] = shown_prompt
            with st.container(height=180, border=True):
                st.code(shown_prompt, language="text")


def symbol_report_prompt_parts(store: SQLiteStore, symbol: str) -> tuple[str, Dossier]:
    """Refresh one symbol's pages; return its decision prompt and dossier."""
    rows, _, _ = store.get_stocks(filters={"symbol": {"values": [symbol]}}, page_size=1)
    row = rows[0] if rows else {}
    overview_data, _ = detail.load_page(store, symbol, "overview", force=True)
    statistics_data, _ = detail.load_page(store, symbol, "statistics", force=True)
    forecast_data, _ = detail.load_page(store, symbol, "forecast", force=True)

    statements: dict[str, dict[str, Any]] = {}
    # The gates read underscore names; provider pages use display names.
    statement_keys = {
        "income-statement": "income",
        "balance-sheet": "balance",
        "cash-flow-statement": "cash",
        "ratios": "ratios",
    }
    for statement in detail.STATEMENTS:
        for period in ("annual", "quarterly"):
            data, _ = detail.load_page(
                store,
                symbol,
                "financials",
                statement=statement,
                period=period,
                force=True,
            )
            statements[f"{statement_keys[statement]}_{period}"] = (
                detail_parse.parse_statement(data) or {} if data else {}
            )

    peers, _, _ = store.get_stocks(page_size=0)
    stamp = None
    if hasattr(store, "get_metadata"):
        raw_stamp = store.get_metadata("last_successful_sync_at")
        if raw_stamp:
            try:
                stamp = datetime.fromtimestamp(float(raw_stamp), UTC).isoformat()
            except (TypeError, ValueError):
                stamp = None

    overview = detail_parse.parse_overview(overview_data) if overview_data else None
    statistics = (
        detail_parse.parse_statistics(statistics_data) if statistics_data else None
    )
    forecast = detail_parse.parse_forecast(forecast_data) if forecast_data else None
    built = dossier.build_dossier(
        symbol,
        row=row,
        overview=overview,
        forecast=forecast,
        statements=statements,
        peers=peers,
        as_of=stamp,
        today=datetime.fromisoformat(stamp).date() if stamp else None,
    )
    prompt = report.symbol_report_prompt(
        symbol,
        row=row,
        overview=overview,
        statistics=statistics,
        forecast=forecast,
        statements=statements,
        history=detail.load_history(store, symbol, "1Y"),
        dossier=built,
    )
    return prompt, built


def symbol_report_prompt_for(
    store: SQLiteStore,
    symbol: str,
    *,
    on_dossier: Callable[[Dossier], None] | None = None,
) -> str:
    """Build the prompt on demand, handing its dossier to the optional callback."""
    prompt, built = symbol_report_prompt_parts(store, symbol)
    if on_dossier is not None:
        on_dossier(built)
    return prompt


def render_symbol_report(store: SQLiteStore, symbol: str) -> None:
    """The per-symbol investment report shown above the detail sections."""
    dossier_key = f"symbol-{symbol}-dossier"

    def capture(built: Dossier) -> None:
        st.session_state[dossier_key] = built

    def show_dossier() -> None:
        built = st.session_state.get(dossier_key)
        if built is not None:
            deepdive_view.render_deep_dive(store, symbol, built)

    render_llm_report(
        scope_key=f"symbol-{symbol}-llm-report",
        heading="🤖 AI report",
        prompt_factory=lambda: symbol_report_prompt_for(
            store, symbol, on_dossier=capture
        ),
        caption=lambda model: (
            f"Model: {model} — freshly fetched data for {symbol} is sent."
        ),
        system_instruction=report.SYMBOL_SYSTEM_INSTRUCTION,
        max_tokens=SYMBOL_MAX_TOKENS,
        before_report=show_dossier,
    )
