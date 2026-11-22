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

from stonks.backtest import REBALANCE_LABELS, run_backtest
from stonks.detail_view import sparkline_svg
from stonks.store import SQLiteStore

PORTFOLIO_VISUALIZER_URL = "https://www.portfoliovisualizer.com/backtest-portfolio"
DEFAULT_SYMBOLS: tuple[str, ...] = ("VUAA", "GOOGL", "NVDA", "CROX")
DEFAULT_BENCHMARK = "VUAA"
_RESULT_KEY = "backtest_result"
_SETTINGS_KEY = "backtest_settings"
_PENDING_LOAD_KEY = "backtest_pending_load"
_SAVE_NAME_KEY = "backtest_save_name"
_WIDGET_KEYS = (
    "bt_editor",
    "bt_benchmark",
    "bt_initial",
    "bt_start",
    "bt_end",
    "bt_rebalance",
)
_LABEL_TO_KEY = {label: key for key, label in REBALANCE_LABELS.items()}


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
    rows: list[dict[str, Any]],
) -> tuple[list[str], list[float] | None]:
    """Read the portfolio editor's rows into symbols and optional weights.

    Blank weights mean equal weight when the whole column is blank.

    Raises:
        ValueError: when a symbol repeats or only some rows carry a weight.
    """
    symbols: list[str] = []
    weights: list[float | None] = []
    for row in rows:
        symbol = str(row.get("Symbol") or "").strip().upper()
        if not symbol:
            continue
        if symbol in symbols:
            raise ValueError(f"{symbol} appears twice.")
        raw = row.get("Weight %")
        weight: float | None
        if raw is None or (isinstance(raw, float) and pd.isna(raw)) or raw == "":
            weight = None
        else:
            weight = float(raw)
            if weight <= 0:
                raise ValueError(f"Weight for {symbol} must be positive.")
        symbols.append(symbol)
        weights.append(weight)

    if not symbols:
        raise ValueError("Add at least one symbol.")
    if all(weight is None for weight in weights):
        return symbols, None
    if any(weight is None for weight in weights):
        raise ValueError("Give a weight for every symbol, or leave them all blank.")
    return symbols, weights  # type: ignore[return-value]


def default_settings() -> dict[str, Any]:
    """The portfolio the tab opens with, editable like any other."""
    return {
        "symbols": list(DEFAULT_SYMBOLS),
        "weights": None,
        "benchmark": DEFAULT_BENCHMARK,
        "initial": 10_000.0,
        "start": dt.date(2017, 1, 1),
        "end": dt.date.today(),
        "rebalance": "annual",
    }


def _settings_from_widgets(
    rows: list[dict[str, Any]],
    benchmark: str,
    initial: float,
    start: dt.date,
    end: dt.date,
    rebalance: str,
) -> dict[str, Any]:
    symbols, weights = parse_portfolio(rows)
    return {
        "symbols": symbols,
        "weights": weights,
        "benchmark": benchmark.strip().upper(),
        "initial": float(initial),
        "start": start,
        "end": end,
        "rebalance": rebalance,
    }


def _portfolio_rows(settings: dict[str, Any]) -> list[dict[str, Any]]:
    weights = settings.get("weights") or [None] * len(settings["symbols"])
    return [
        {"Symbol": symbol, "Weight %": weight}
        for symbol, weight in zip(settings["symbols"], weights, strict=True)
    ]


def _as_date(value: Any, fallback: dt.date) -> dt.date:
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return fallback


def _describe_settings(settings: dict[str, Any]) -> str:
    """One-line summary for a saved portfolio card."""
    weights = settings.get("weights")
    if weights:
        allocation = " · ".join(
            f"{symbol} {weight:g}%"
            for symbol, weight in zip(settings["symbols"], weights)
        )
    else:
        allocation = " · ".join(f"{symbol} equal" for symbol in settings["symbols"])
    benchmark = f" — vs {settings['benchmark']}" if settings.get("benchmark") else ""
    return f"{allocation}{benchmark}"


def _growth_svg(
    portfolio: list[dict[str, Any]], benchmark: list[dict[str, Any]] | None
) -> str:
    """Inline SVG growth curve, with the benchmark as a dashed grey line."""
    if len(portfolio) < 2:
        return ""
    width, height, pad = 720, 160, 4.0
    months = [str(point["date"]) for point in portfolio]
    values = {str(point["date"]): float(point["value"]) for point in portfolio}
    bench_values = (
        {str(point["date"]): float(point["value"]) for point in benchmark}
        if benchmark
        else {}
    )
    low = min(values.values())
    high = max(values.values())
    if bench_values:
        low = min(low, min(bench_values.values()))
        high = max(high, max(bench_values.values()))
    span = high - low or 1.0
    step = (width - 2 * pad) / (len(months) - 1)

    def y(value: float) -> float:
        return height - pad - (value - low) / span * (height - 2 * pad)

    def line(points: list[tuple[float, float]]) -> str:
        return " ".join(f"{x:.1f},{yv:.1f}" for x, yv in points)

    portfolio_line = line(
        [(pad + index * step, values[m]) for index, m in enumerate(months)]
    )
    area = (
        f"{pad:.1f},{height - pad:.1f} {portfolio_line} "
        f"{width - pad:.1f},{height - pad:.1f}"
    )
    benchmark_line = ""
    if bench_values:
        points = [
            (pad + index * step, bench_values[month])
            for index, month in enumerate(months)
            if month in bench_values
        ]
        if len(points) > 1:
            benchmark_line = (
                f'<polyline points="{line(points)}" fill="none" stroke="#94a3b8" '
                'stroke-width="1.6" stroke-dasharray="5 4" stroke-linejoin="round" />'
            )
    return (
        f'<svg class="sk-spark" viewBox="0 0 {width} {height}" '
        'preserveAspectRatio="none" role="img" aria-label="Portfolio growth">'
        f'<polygon points="{area}" fill="rgba(99, 102, 241, 0.12)" />'
        f"{benchmark_line}"
        f'<polyline points="{portfolio_line}" fill="none" stroke="#6366f1" '
        'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" /></svg>'
    )


def _html(markup: str) -> None:
    """Render card markup as HTML (markdown would treat it as code)."""
    st.html(markup.strip())


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

    allocation = " · ".join(
        f"{symbol} {weight:.0f}%" for symbol, weight in result["weights"].items()
    )
    benchmark = result.get("benchmark")
    comparison = f" · vs {benchmark['symbol']}" if benchmark else ""
    st.caption(
        f"{result['start']} → {result['end']} · {allocation} · "
        f"{REBALANCE_LABELS[result['rebalance']]} · "
        f"${result['initial']:,.0f} invested{comparison}"
    )
    if result.get("benchmark_error"):
        st.warning(result["benchmark_error"])

    yearly = result["yearly"]
    pills = (
        _pill("CAGR", f"{result['cagr_pct']:+.2f}%", _direction(result["cagr_pct"]))
        + _pill(
            "Total return",
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
            "Max drawdown",
            f"{result['max_drawdown_pct']:.1f}%",
            _direction(result["max_drawdown_pct"]),
        )
        + _pill(
            "Best / worst year",
            f"{result['best_year_pct']:+.1f}% / {result['worst_year_pct']:+.1f}%",
        )
    )
    if benchmark:
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

    closes = [float(point["value"]) for point in result["curve"]]
    chart = _growth_svg(
        result["curve"], benchmark["curve"] if benchmark else None
    ) or sparkline_svg(closes)
    _html(
        '<div class="sk-card"><div class="sk-card-title">Growth of the portfolio</div>'
        f'<div class="sk-chart">{chart}</div>'
        '<div class="sk-range-labels">'
        f"<span>{result['start']}</span>"
        f'<span class="sk-chart-change {_direction(result["total_return_pct"])}">'
        f"{result['total_return_pct']:+.1f}%</span>"
        f"<span>{result['end']}</span></div></div>"
    )

    if yearly:
        bench_yearly = (
            {row["year"]: row["return_pct"] for row in benchmark["yearly"]}
            if benchmark
            else {}
        )
        rows: list[dict[str, Any]] = []
        for row in yearly:
            entry: dict[str, Any] = {
                "Year": row["year"],
                "Portfolio %": round(row["return_pct"], 2),
            }
            if benchmark:
                bench_value = bench_yearly.get(row["year"])
                entry[f"{benchmark['symbol']} %"] = (
                    round(bench_value, 2) if bench_value is not None else None
                )
            rows.append(entry)
        st.dataframe(rows, hide_index=True, use_container_width=True)

    st.caption(
        "Dividends are reinvested and prices are adjusted closes. The same "
        "portfolio can be reproduced on Portfolio Visualizer with the "
        "allocation above."
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
        if st.button("💾 Save Current Settings", use_container_width=True):
            settings = st.session_state.get(_SETTINGS_KEY)
            if not name.strip():
                st.warning("Please enter a name.")
            elif not settings:
                st.warning("Run the backtest once, then save its settings.")
            else:
                store.save_backtest(name.strip(), settings)
                st.toast(f"✅ Portfolio '{name.strip()}' saved!", icon="💾")
                st.rerun()


def render_backtest_tab(store: SQLiteStore) -> None:
    """Render the backtest tab: portfolio inputs on top, results below."""
    st.markdown(
        '<div class="section-header">🧪 Portfolio Backtest</div>',
        unsafe_allow_html=True,
    )
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
    settings = st.session_state.get(_SETTINGS_KEY) or default_settings()

    _render_saved(store)

    rows = pd.DataFrame(
        _portfolio_rows(settings),
        columns=["Symbol", "Weight %"],
    )
    with st.form("backtest_form"):
        edited = st.data_editor(
            rows,
            key="bt_editor",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "Symbol": st.column_config.TextColumn(
                    "Symbol", help="Ticker, e.g. VUAA", required=True
                ),
                "Weight %": st.column_config.NumberColumn(
                    "Weight %",
                    help="Optional; blank means equal weight",
                    min_value=0.0,
                    step=5.0,
                    format="%g",
                ),
            },
        )
        benchmark_col, initial_col = st.columns(2)
        benchmark = benchmark_col.text_input(
            "Benchmark",
            value=str(settings.get("benchmark") or ""),
            help="Compared on the same window; blank to skip",
        )
        initial = initial_col.number_input(
            "Initial amount",
            min_value=100.0,
            value=float(settings.get("initial", 10_000.0)),
            step=1_000.0,
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
                edited.to_dict("records"),
                benchmark,
                float(initial),
                start,
                end,
                _LABEL_TO_KEY[rebalance_label],
            )
            if start > end:
                raise ValueError("The start date is after the end date.")
        except ValueError as exc:
            st.session_state[_RESULT_KEY] = None
            st.error(str(exc))
        else:
            with st.spinner("Backtesting…"):
                st.session_state[_RESULT_KEY] = run_backtest(
                    store,
                    current["symbols"],
                    current["weights"],
                    rebalance=current["rebalance"],
                    start=start.isoformat(),
                    end=end.isoformat(),
                    initial=current["initial"],
                    benchmark=current["benchmark"] or None,
                )
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
