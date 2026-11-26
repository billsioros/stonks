"""Streamlit view for the portfolio backtest tab.

Runs :mod:`stonks.backtest` over the rows of an editable portfolio table and
shows the result as the same flat cards the detail page uses. Portfolios can be
saved, loaded and deleted like screener presets, and the tab opens with a
default four-symbol portfolio. Portfolio Visualizer is linked rather than
embedded: it has no public API, and the calculation here is the app's own so the
numbers can be reproduced offline.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import streamlit as st

from stonks.backtest import CONTRIBUTION_MONTHS, REBALANCE_LABELS, run_backtest
from stonks.charts import growth_figure
from stonks.correlation import portfolio_correlation_factor
from stonks.portfolio import PortfolioSummary, backtest_allocation, portfolio_snapshot
from stonks.store import SQLiteStore

PORTFOLIO_VISUALIZER_URL = "https://www.portfoliovisualizer.com/backtest-portfolio"
DEFAULT_SYMBOLS: tuple[str, ...] = ("VUAA", "GOOGL", "NVDA", "CROX")
DEFAULT_BENCHMARKS: tuple[str, ...] = ("VUAA", "QQQ")
_RESULT_KEY = "backtest_result"
_SETTINGS_KEY = "backtest_settings"
_PENDING_LOAD_KEY = "backtest_pending_load"
_SAVE_NAME_KEY = "backtest_save_name"
_WIDGET_KEYS = (
    "bt_symbol_ticker",
    "bt_symbol_allocation",
    "bt_edit_index",
    "bt_allocation_mode",
    "bt_contribution",
    "bt_contribution_frequency",
    "bt_benchmark",
    "bt_initial",
    "bt_start",
    "bt_end",
    "bt_rebalance",
)
_LABEL_TO_KEY = {label: key for key, label in REBALANCE_LABELS.items()}
_ALLOCATION_MODES = {"percent": "Percent", "amount": "Fixed amount"}


def _cadence_label(key: str) -> str:
    return "None" if key == "none" else REBALANCE_LABELS[key]


def format_allocation(result: dict[str, Any]) -> str:
    """Allocation caption for a backtest result, in either allocation mode."""
    if result.get("allocation_mode") == "amount":
        amounts = result.get("contributions") or {}
        parts = [f"{symbol} {amount:g}" for symbol, amount in amounts.items()]
        return f"{' · '.join(parts)} per contribution" if parts else ""
    weights = result.get("weights") or {}
    return " · ".join(f"{symbol} {weight:g}%" for symbol, weight in weights.items())


def parse_symbols(text: str) -> list[str]:
    """Split a comma/space separated ticker list, upper-cased and de-duplicated."""
    symbols: list[str] = []
    for chunk in text.replace(";", ",").split(","):
        for token in chunk.split():
            symbol = token.strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    return symbols


def parse_weights(text: str) -> list[float] | None:
    """Parse ``"60, 40"`` into weights, or ``None`` when the field is blank.

    Raises:
        ValueError: when a token is not a positive number.
    """
    tokens = [
        token for token in text.replace("%", " ").replace(",", " ").split() if token
    ]
    if not tokens:
        return None
    weights: list[float] = []
    for token in tokens:
        try:
            value = float(token)
        except ValueError as exc:
            raise ValueError(f"Not a number: {token}") from exc
        if value <= 0:
            raise ValueError("Weights must be positive")
        weights.append(value)
    return weights


def parse_portfolio(
    rows: list[dict[str, Any]], mode: str = "percent"
) -> tuple[list[str], list[float] | None]:
    """Read the portfolio editor's rows into symbols and allocations.

    Percent mode treats blank cells as equal weight when the whole column is
    blank. Amount mode requires a positive sum in every row.

    Raises:
        ValueError: when a symbol repeats or an allocation is missing or invalid.
    """
    if mode not in _ALLOCATION_MODES:
        raise ValueError(f"Unknown allocation mode: {mode}")
    keys = (
        ("Amount", "Allocation", "Weight %")
        if mode == "amount"
        else (
            "Allocation",
            "Weight %",
            "Amount",
        )
    )
    symbols: list[str] = []
    values: list[float | None] = []
    for row in rows:
        raw_symbol = row.get("Symbol")
        if raw_symbol is None or str(raw_symbol).strip() == "":
            raw_symbol = row.get("Allocation")
        symbol = str(raw_symbol).strip().upper() if isinstance(raw_symbol, str) else ""
        if not symbol:
            continue
        if symbol in symbols:
            raise ValueError(f"{symbol} appears twice.")
        raw = next((row[key] for key in keys if key in row), None)
        value: float | None
        if raw is None or (isinstance(raw, float) and pd.isna(raw)) or raw == "":
            value = None
        else:
            value = float(raw)
            if value <= 0:
                label = "Amount" if mode == "amount" else "Weight"
                raise ValueError(f"{label} for {symbol} must be positive.")
        symbols.append(symbol)
        values.append(value)

    if not symbols:
        raise ValueError("Add at least one symbol.")
    if mode == "amount":
        if any(value is None for value in values):
            raise ValueError("Give an amount for every symbol.")
        return symbols, values  # type: ignore[return-value]
    if all(value is None for value in values):
        return symbols, None
    if any(value is None for value in values):
        raise ValueError("Give a weight for every symbol, or leave them all blank.")
    return symbols, values  # type: ignore[return-value]


def default_settings() -> dict[str, Any]:
    """The portfolio the tab opens with, editable like any other."""
    return {
        "symbols": list(DEFAULT_SYMBOLS),
        "weights": None,
        "benchmark": ", ".join(DEFAULT_BENCHMARKS),
        "initial": 10_000.0,
        "start": dt.date(2017, 1, 1),
        "end": dt.date.today(),
        "rebalance": "annual",
        "allocation_mode": "percent",
        "contribution": 500.0,
        "contribution_frequency": "monthly",
    }


def _settings_from_widgets(
    rows: list[dict[str, Any]],
    benchmark: str,
    initial: float,
    start: dt.date,
    end: dt.date,
    rebalance: str,
    allocation_mode: str,
    contribution: float,
    contribution_frequency: str,
) -> dict[str, Any]:
    symbols, weights = parse_portfolio(rows, mode=allocation_mode)
    return {
        "symbols": symbols,
        "weights": weights,
        "benchmark": benchmark.strip().upper(),
        "initial": float(initial),
        "start": start,
        "end": end,
        "rebalance": rebalance,
        "allocation_mode": allocation_mode,
        "contribution": float(contribution),
        "contribution_frequency": contribution_frequency,
    }


def _portfolio_rows(settings: dict[str, Any]) -> list[dict[str, Any]]:
    weights = settings.get("weights") or [None] * len(settings["symbols"])
    return [
        {"Symbol": symbol, "Allocation": weight}
        for symbol, weight in zip(settings["symbols"], weights, strict=True)
    ]


def _contribution_amounts(settings: dict[str, Any]) -> list[float] | None:
    """Split the configured cash arrival across the portfolio's symbols."""
    if settings.get("contribution_frequency", "none") == "none":
        return None
    weights = settings.get("weights") or [1.0] * len(settings["symbols"])
    if settings.get("allocation_mode") == "amount":
        return [float(weight) for weight in weights]
    total = float(settings.get("contribution") or 0.0)
    if total <= 0:
        return None
    weight_total = sum(weights)
    return [total * weight / weight_total for weight in weights]


def _as_date(value: Any, fallback: dt.date) -> dt.date:
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return fallback


def holdings_settings_from_summary(summary: PortfolioSummary) -> dict[str, Any] | None:
    """Seed editable backtest settings from priced holdings' market values."""
    symbols, weights = backtest_allocation(summary)
    if not symbols:
        return None
    return {**default_settings(), "symbols": symbols, "weights": weights}


def holdings_settings(store: SQLiteStore) -> dict[str, Any] | None:
    """Seed settings from stored lots, without fetching daily history."""
    summary, _ = portfolio_snapshot(store, include_history=False)
    return holdings_settings_from_summary(summary)


def run_configured_backtest(
    store: SQLiteStore, settings: dict[str, Any]
) -> dict[str, Any]:
    """Run the form's settings and attach the allocation's correlation factor."""
    contributions = _contribution_amounts(settings)
    initial = float(settings["initial"])
    if initial <= 0 and not contributions:
        raise ValueError("Add an initial amount or a recurring contribution.")
    current = {
        **settings,
        "contribution": float(sum(contributions)) if contributions else 0.0,
    }
    result = run_backtest(
        store,
        current["symbols"],
        current["weights"],
        rebalance=current["rebalance"],
        start=_as_date(current["start"], dt.date(2017, 1, 1)).isoformat(),
        end=_as_date(current["end"], dt.date.today()).isoformat(),
        initial=initial,
        benchmark=current.get("benchmark") or None,
        contributions=contributions,
        frequency=current.get("contribution_frequency", "monthly"),
    )
    result["allocation_mode"] = current.get("allocation_mode", "percent")
    if "error" not in result:
        result["correlation_factor"] = portfolio_correlation_factor(
            store,
            result["symbols"],
            [result["weights"][symbol] for symbol in result["symbols"]],
        )
    return result


def _describe_settings(settings: dict[str, Any]) -> str:
    """One-line summary for a saved portfolio card."""
    weights = settings.get("weights")
    amount_mode = settings.get("allocation_mode") == "amount"
    if weights and amount_mode:
        allocation = " · ".join(
            f"{symbol} {weight:g}"
            for symbol, weight in zip(settings["symbols"], weights)
        )
    elif weights:
        allocation = " · ".join(
            f"{symbol} {weight:g}%"
            for symbol, weight in zip(settings["symbols"], weights)
        )
    else:
        allocation = " · ".join(f"{symbol} equal" for symbol in settings["symbols"])
    frequency = settings.get("contribution_frequency", "none")
    if frequency != "none":
        amounts = _contribution_amounts(settings)
        total = sum(amounts) if amounts else 0.0
        cadence = "off" if total == 0 else _cadence_label(frequency).lower()
        allocation += f" · {total:g} {cadence}"
        if amount_mode:
            allocation += " (fixed amounts)"
    benchmark = f" — vs {settings['benchmark']}" if settings.get("benchmark") else ""
    return f"{allocation}{benchmark}"


def _html(markup: str) -> None:
    """Render card markup as raw HTML, as the other views do."""
    st.markdown(markup.strip(), unsafe_allow_html=True)


def _pill(label: str, value: str, direction: str = "") -> str:
    return (
        f'<div class="sk-pill"><span class="sk-pill-label">{label}</span>'
        f'<span class="sk-pill-value {direction}">{value}</span></div>'
    )


def _direction(value: float | None) -> str:
    if value is None or value == 0:
        return ""
    return "up" if value > 0 else "down"


def _render_result(result: dict[str, Any]) -> None:
    """Metrics, growth curve and yearly returns for one finished backtest."""
    if "error" in result:
        st.warning(result["error"])
        return

    allocation = format_allocation(result)
    frequency = result.get("frequency", "none")
    active = frequency != "none" and result.get("contribution", 0.0) > 0
    contributions = f" · {_cadence_label(frequency)} contributions" if active else ""
    benchmarks = result.get("benchmarks") or (
        [result["benchmark"]] if result.get("benchmark") else []
    )
    comparison = (
        " · vs " + ", ".join(item["symbol"] for item in benchmarks)
        if benchmarks
        else ""
    )
    st.caption(
        f"{result['start']} → {result['end']} · {allocation} · "
        f"{REBALANCE_LABELS[result['rebalance']]}{contributions} · "
        f"${result['invested']:,.0f} invested{comparison}"
    )
    if result.get("benchmark_error"):
        st.warning(result["benchmark_error"])

    yearly = result["yearly"]
    correlation = result.get("correlation_factor")
    prefix = "Time-weighted " if active else ""
    st.markdown('<div class="bt-section">Key metrics</div>', unsafe_allow_html=True)
    pills = (
        _pill(
            f"{prefix}CAGR",
            f"{result['cagr_pct']:+.2f}%",
            _direction(result["cagr_pct"]),
        )
        + _pill(
            f"{prefix}Total return",
            f"{result['total_return_pct']:+.1f}%",
            _direction(result["total_return_pct"]),
        )
        + _pill(
            "End value",
            f"${result['final']:,.0f}",
            _direction(result["total_return_pct"]),
        )
        + _pill(
            "Volatility",
            f"{result['stdev_pct']:.1f}%" if result["stdev_pct"] is not None else "—",
        )
        + _pill(
            "Portfolio correlation",
            f"{correlation:+.2f}" if correlation is not None else "—",
            _direction(correlation),
        )
        + _pill(
            "Max drawdown",
            f"{result['max_drawdown_pct']:.1f}%",
            _direction(result["max_drawdown_pct"]),
        )
        + _pill(
            "Best / worst year",
            f"{result['best_year_pct']:+.1f}% / {result['worst_year_pct']:+.1f}%",
        )
    )
    if active:
        money_weighted = result.get("money_weighted_cagr_pct")
        pills += _pill("Total invested", f"${result['invested']:,.0f}") + _pill(
            "Money-weighted",
            f"{money_weighted:+.2f}%" if money_weighted is not None else "—",
            _direction(money_weighted),
        )
    for benchmark in benchmarks:
        spread = result["cagr_pct"] - benchmark["cagr_pct"]
        pills += _pill(
            f"{benchmark['symbol']} CAGR",
            f"{benchmark['cagr_pct']:+.2f}%",
            _direction(benchmark["cagr_pct"]),
        ) + _pill(
            "vs benchmark",
            f"{spread:+.2f}pp",
            _direction(spread),
        )
    _html('<div class="sk-card"><div class="sk-pills">' + pills + "</div></div>")

    st.caption("Growth of the portfolio")
    st.plotly_chart(growth_figure(result), width="stretch")

    if yearly:
        bench_yearly = [
            {row["year"]: row["return_pct"] for row in item["yearly"]}
            for item in benchmarks
        ]
        rows: list[dict[str, Any]] = []
        for row in yearly:
            entry: dict[str, Any] = {
                "Year": row["year"],
                "Portfolio %": round(row["return_pct"], 2),
            }
            for benchmark, values in zip(benchmarks, bench_yearly):
                bench_value = values.get(row["year"])
                entry[f"{benchmark['symbol']} %"] = (
                    round(bench_value, 2) if bench_value is not None else None
                )
            rows.append(entry)
        st.caption("Annual returns")
        st.dataframe(rows, hide_index=True, width="stretch")

    st.caption(
        "Dividends are reinvested and prices are adjusted closes. Returns are "
        "time-weighted. The same portfolio can be reproduced on Portfolio "
        "Visualizer with the allocation above."
    )
    st.link_button("Open in Portfolio Visualizer ↗", PORTFOLIO_VISUALIZER_URL)


def _render_saved(store: SQLiteStore) -> None:
    """Saved portfolios: load, delete, and save the last run's settings."""
    with st.expander("💾 Saved Portfolios", expanded=False):
        saved = store.list_backtests()
        if not saved:
            st.caption("No saved portfolios yet.")
        for item in saved:
            cols = st.columns([6, 1, 1])
            with cols[0]:
                st.markdown(f"**{item['name']}**")
                st.caption(_describe_settings(item["settings"]))
            with cols[1]:
                if st.button("▶", key=f"load_bt_{item['name']}", help="Load"):
                    st.session_state[_PENDING_LOAD_KEY] = item["settings"]
                    st.rerun()
            with cols[2]:
                if st.button("🗑", key=f"del_bt_{item['name']}", help="Delete"):
                    store.delete_backtest(item["name"])
                    st.rerun()

        st.divider()
        name = st.text_input(
            "Portfolio name", key=_SAVE_NAME_KEY, placeholder="My Portfolio"
        )
        if st.button("💾 Save Current Settings", width="stretch"):
            settings = st.session_state.get(_SETTINGS_KEY)
            if not name.strip():
                st.warning("Please enter a name.")
            elif not settings:
                st.warning("Run the backtest once, then save its settings.")
            else:
                store.save_backtest(name.strip(), settings)
                st.toast(f"✅ Portfolio '{name.strip()}' saved!", icon="💾")
                st.rerun()


def _clear_symbol_editor_state() -> None:
    """Forget the add/edit form so the next open starts clean."""
    for key in ("bt_symbol_ticker", "bt_symbol_allocation", "bt_edit_index"):
        st.session_state.pop(key, None)


def _commit_symbol(
    settings: dict[str, Any],
    rows: list[dict[str, Any]],
    current_mode: str,
    editing: int | None,
) -> None:
    """Validate the editor form, then write the portfolio back to session state."""
    ticker = parse_symbols(str(st.session_state.get("bt_symbol_ticker") or ""))
    if len(ticker) != 1:
        st.warning("Enter one ticker symbol.")
        return

    allocation = float(st.session_state.get("bt_symbol_allocation") or 0.0)
    if current_mode == "percent" and allocation == 0:
        allocation = None  # type: ignore[assignment]
    candidate = list(rows)
    new_row = {"Symbol": ticker[0], "Allocation": allocation}
    if editing is None:
        candidate.append(new_row)
    else:
        candidate[editing] = new_row

    try:
        symbols, weights = parse_portfolio(candidate, mode=current_mode)
    except ValueError as exc:
        st.warning(str(exc))
        return

    settings["symbols"] = symbols
    settings["weights"] = weights
    settings["allocation_mode"] = current_mode
    st.session_state[_SETTINGS_KEY] = settings
    _clear_symbol_editor_state()
    st.rerun()


def _render_symbol_editor(
    settings: dict[str, Any], current_mode: str
) -> list[dict[str, Any]]:
    """Render a roomies-style symbol list with inline edit/delete and add panel."""
    rows = _portfolio_rows(settings)
    amount_mode = current_mode == "amount"
    st.caption(
        f"{len(rows)} symbols"
        + (
            " · 0 means equal weight when every weight is blank"
            if not amount_mode
            else " · amount added at every contribution"
        )
    )
    if not rows:
        st.caption("No symbols yet. Add one below.")

    for index, row in enumerate(rows):
        allocation = row["Allocation"]
        if allocation is None:
            display = "equal weight" if not amount_mode else "set amount"
        elif amount_mode:
            display = f"${allocation:g}"
        else:
            display = f"{allocation:g}%"
        cols = st.columns([3, 2, 1, 1])
        cols[0].markdown(f"**{row['Symbol']}**")
        cols[1].caption(display)
        if cols[2].button("✏️", key=f"bt_edit_symbol_{index}", help="Edit this symbol"):
            st.session_state["bt_symbol_ticker"] = row["Symbol"]
            st.session_state["bt_symbol_allocation"] = (
                0.0 if allocation is None else float(allocation)
            )
            st.session_state["bt_edit_index"] = index
            st.rerun()
        if cols[3].button(
            "🗑", key=f"bt_delete_symbol_{index}", help="Remove this symbol"
        ):
            remaining = [item for i, item in enumerate(rows) if i != index]
            symbols, weights = (
                parse_portfolio(remaining, mode=current_mode)
                if remaining
                else ([], None)
            )
            settings["symbols"] = symbols
            settings["weights"] = weights
            settings["allocation_mode"] = current_mode
            st.session_state[_SETTINGS_KEY] = settings
            _clear_symbol_editor_state()
            st.rerun()

    editing = st.session_state.get("bt_edit_index")
    editing = int(editing) if editing is not None else None
    if editing is not None and not 0 <= editing < len(rows):
        editing = None
    label = "Edit symbol" if editing is not None else "Add symbol"

    with st.expander(label, expanded=editing is not None):
        st.text_input(
            "Ticker",
            value=rows[editing]["Symbol"] if editing is not None else "",
            key="bt_symbol_ticker",
            placeholder="VUAA",
        )
        current_allocation = (
            rows[editing]["Allocation"] if editing is not None else None
        )
        st.number_input(
            "Amount per contribution" if amount_mode else "Weight %",
            min_value=0.0,
            value=0.0 if current_allocation is None else float(current_allocation),
            step=100.0 if amount_mode else 5.0,
            key="bt_symbol_allocation",
            help=(
                "Positive amount added at every contribution"
                if amount_mode
                else "Leave 0 to split the contribution equally"
            ),
        )
        action_col, cancel_col = st.columns([1, 1])
        with action_col:
            if st.button(
                "Save changes" if editing is not None else "Add",
                key="bt_symbol_save",
            ):
                _commit_symbol(settings, rows, current_mode, editing)
        if editing is not None:
            with cancel_col:
                if st.button("Cancel", key="bt_symbol_cancel"):
                    _clear_symbol_editor_state()
                    st.rerun()

    return rows


def render_backtest_tab(store: SQLiteStore) -> None:
    """Render the backtest tab: portfolio inputs on top, results below."""
    st.caption(
        "Total-return backtest over StockAnalysis adjusted monthly closes — "
        "at most ten years of history."
    )

    pending = st.session_state.pop(_PENDING_LOAD_KEY, None)
    if pending:
        for key in _WIDGET_KEYS:
            st.session_state.pop(key, None)
        st.session_state[_SETTINGS_KEY] = {
            **default_settings(),
            **pending,
            "start": _as_date(pending.get("start"), dt.date(2017, 1, 1)),
            "end": _as_date(pending.get("end"), dt.date.today()),
        }
    if _SETTINGS_KEY not in st.session_state:
        st.session_state[_SETTINGS_KEY] = holdings_settings(store) or default_settings()
    settings = st.session_state.get(_SETTINGS_KEY) or default_settings()
    if settings.get("allocation_mode") not in _ALLOCATION_MODES:
        settings["allocation_mode"] = "percent"

    st.markdown('<div class="bt-section">Setup</div>', unsafe_allow_html=True)
    _render_saved(store)

    mode_options = list(_ALLOCATION_MODES)
    mode_labels = list(_ALLOCATION_MODES.values())
    mode_label = st.radio(
        "Allocation mode",
        mode_labels,
        index=mode_options.index(settings["allocation_mode"]),
        key="bt_allocation_mode",
    )
    current_mode = mode_options[mode_labels.index(mode_label)]
    amount_mode = current_mode == "amount"
    settings["allocation_mode"] = current_mode

    rows = _render_symbol_editor(settings, current_mode)
    with st.form("backtest_form"):
        contribution_col, frequency_col = st.columns(2)
        contribution = contribution_col.number_input(
            "Contribution per period",
            min_value=0.0,
            value=float(settings.get("contribution", 0.0)),
            step=100.0,
            disabled=amount_mode,
            help="Split across the portfolio in percent mode",
            key="bt_contribution",
        )
        frequency_options = list(CONTRIBUTION_MONTHS)
        saved_frequency = settings.get("contribution_frequency", "monthly")
        frequency = frequency_col.selectbox(
            "Contribution cadence",
            frequency_options,
            index=frequency_options.index(saved_frequency)
            if saved_frequency in frequency_options
            else frequency_options.index("monthly"),
            format_func=_cadence_label,
            key="bt_contribution_frequency",
        )
        benchmark_col, initial_col = st.columns(2)
        benchmark = benchmark_col.text_input(
            "Benchmarks",
            value=str(settings.get("benchmark") or ""),
            help="Comma-separated tickers compared on the same window; blank to skip",
            key="bt_benchmark",
        )
        initial = initial_col.number_input(
            "Initial amount",
            min_value=0.0,
            value=float(settings.get("initial", 10_000.0)),
            step=1_000.0,
            help="May be zero when only recurring contributions are used",
        )
        start_col, end_col, rebalance_col = st.columns(3)
        start = start_col.date_input(
            "Start", value=_as_date(settings.get("start"), dt.date(2017, 1, 1))
        )
        end = end_col.date_input(
            "End", value=_as_date(settings.get("end"), dt.date.today())
        )
        rebalance_label = rebalance_col.selectbox(
            "Rebalance",
            list(REBALANCE_LABELS.values()),
            index=list(REBALANCE_LABELS).index(settings.get("rebalance", "annual")),
        )
        submitted = st.form_submit_button("Run backtest")

    if submitted:
        try:
            current = _settings_from_widgets(
                rows,
                benchmark,
                float(initial),
                start,
                end,
                _LABEL_TO_KEY[rebalance_label],
                current_mode,
                float(contribution),
                frequency,
            )
            if start > end:
                raise ValueError("The start date is after the end date.")
            contributions = _contribution_amounts(current)
            current["contribution"] = (
                float(sum(contributions)) if contributions else 0.0
            )
            if current["initial"] <= 0 and not contributions:
                raise ValueError("Add an initial amount or a recurring contribution.")
        except ValueError as exc:
            st.session_state[_RESULT_KEY] = None
            st.error(str(exc))
        else:
            with st.spinner("Backtesting…"):
                result = run_configured_backtest(store, current)
                st.session_state[_RESULT_KEY] = result
            st.session_state[_SETTINGS_KEY] = current

    result = st.session_state.get(_RESULT_KEY)
    if result:
        _render_result(result)
    else:
        st.caption(
            "Edit the portfolio and run the backtest. Portfolio Visualizer "
            "offers the same analysis with more asset classes."
        )
        st.link_button("Open Portfolio Visualizer ↗", PORTFOLIO_VISUALIZER_URL)
