"""Streamlit view for the portfolio backtest tab.

Runs :mod:`stonks.backtest` over the symbols and dates the user picks and shows
the result as the same flat cards the detail page uses. Portfolio Visualizer is
linked rather than embedded: it has no public API, and the calculation here is
the app's own so the numbers can be reproduced offline.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import streamlit as st

from stonks.backtest import REBALANCE_LABELS, run_backtest
from stonks.detail_view import sparkline_svg
from stonks.store import SQLiteStore

PORTFOLIO_VISUALIZER_URL = "https://www.portfoliovisualizer.com/backtest-portfolio"
_RESULT_KEY = "backtest_result"
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
    st.caption(
        f"{result['start']} → {result['end']} · {allocation} · "
        f"{REBALANCE_LABELS[result['rebalance']]} · "
        f"${result['initial']:,.0f} invested"
    )

    yearly = result["yearly"]
    _html(
        '<div class="sk-card"><div class="sk-pills">'
        + _pill("CAGR", f"{result['cagr_pct']:+.2f}%", _direction(result["cagr_pct"]))
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
        + "</div></div>"
    )

    closes = [float(point["value"]) for point in result["curve"]]
    _html(
        '<div class="sk-card"><div class="sk-card-title">Growth of the portfolio</div>'
        f'<div class="sk-chart">{sparkline_svg(closes)}</div>'
        '<div class="sk-range-labels">'
        f"<span>{result['start']}</span>"
        f'<span class="sk-chart-change {_direction(result["total_return_pct"])}">'
        f"{result['total_return_pct']:+.1f}%</span>"
        f"<span>{result['end']}</span></div></div>"
    )

    if yearly:
        st.dataframe(
            [
                {"Year": row["year"], "Return %": round(row["return_pct"], 2)}
                for row in yearly
            ],
            hide_index=True,
            use_container_width=True,
        )

    st.caption(
        "Dividends are reinvested and prices are adjusted closes. The same "
        "portfolio can be reproduced on Portfolio Visualizer with the "
        "allocation above."
    )
    st.link_button("Open in Portfolio Visualizer ↗", PORTFOLIO_VISUALIZER_URL)


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

    watchlist = store.get_watchlist_symbols()
    default_symbols = ", ".join(watchlist[:5]) if watchlist else "SPY, BND"

    with st.form("backtest_form"):
        first, second, third = st.columns([2, 1.2, 1])
        symbols_text = first.text_input(
            "Symbols",
            value=default_symbols,
            help="Comma or space separated, e.g. SPY, BND",
        )
        weights_text = second.text_input(
            "Weights %",
            value="",
            help="One per symbol; leave blank for equal weight",
        )
        initial = third.number_input(
            "Initial amount",
            min_value=100.0,
            value=10_000.0,
            step=1_000.0,
        )
        start_col, end_col, rebalance_col = st.columns(3)
        start = start_col.date_input("Start", value=dt.date(2017, 1, 1))
        end = end_col.date_input("End", value=dt.date.today())
        rebalance_label = rebalance_col.selectbox(
            "Rebalance",
            list(REBALANCE_LABELS.values()),
            index=1,
        )
        submitted = st.form_submit_button("Run backtest")

    if submitted:
        symbols = parse_symbols(symbols_text)
        try:
            weights = parse_weights(weights_text)
        except ValueError as exc:
            st.session_state[_RESULT_KEY] = None
            st.error(str(exc))
        else:
            if weights is not None and len(weights) != len(symbols):
                st.session_state[_RESULT_KEY] = None
                st.error("Give one weight per symbol, or none for equal weight.")
            elif start > end:
                st.session_state[_RESULT_KEY] = None
                st.error("The start date is after the end date.")
            else:
                with st.spinner("Backtesting…"):
                    st.session_state[_RESULT_KEY] = run_backtest(
                        store,
                        symbols,
                        weights,
                        rebalance=_LABEL_TO_KEY[rebalance_label],
                        start=start.isoformat(),
                        end=end.isoformat(),
                        initial=float(initial),
                    )

    result = st.session_state.get(_RESULT_KEY)
    if result:
        _render_result(result)
    else:
        st.caption(
            "Pick a few tickers and run the backtest. Portfolio Visualizer "
            "offers the same analysis with more asset classes."
        )
        st.link_button("Open Portfolio Visualizer ↗", PORTFOLIO_VISUALIZER_URL)
