"""Interactive Plotly figures shared by the backtest and detail views."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go  # type: ignore[import-untyped]

_PORTFOLIO_COLOR = "#6366f1"
_BENCHMARK_COLOR = "#94a3b8"
_AREA_COLOR = "rgba(99, 102, 241, 0.12)"
_GRID_COLOR = "rgba(148, 163, 184, 0.16)"


def _line(
    x: list[str],
    y: list[float | None],
    name: str,
    *,
    color: str,
    dash: str | None = None,
    area: bool = False,
) -> go.Scatter:
    line: dict[str, Any] = {"color": color, "width": 2}
    if dash:
        line["dash"] = dash
    return go.Scatter(
        x=x,
        y=y,
        mode="lines",
        name=name,
        line=line,
        fill="tozeroy" if area else None,
        fillcolor=_AREA_COLOR if area else None,
        hovertemplate=f"%{{x}}<br>$%{{y:,.2f}}<extra>{name}</extra>",
        connectgaps=False,
    )


def _style(fig: go.Figure, *, showlegend: bool) -> go.Figure:
    fig.update_layout(
        height=240,
        margin={"l": 4, "r": 4, "t": 8, "b": 4},
        showlegend=showlegend,
        legend={"orientation": "h", "y": 1.18, "x": 0},
        hovermode="x unified",
        plot_bgcolor="rgba(0, 0, 0, 0)",
        paper_bgcolor="rgba(0, 0, 0, 0)",
        xaxis={"showgrid": False, "zeroline": False},
        yaxis={
            "showgrid": True,
            "gridcolor": _GRID_COLOR,
            "zeroline": False,
            "tickprefix": "$",
        },
    )
    return fig


def price_history_figure(history: list[dict[str, Any]]) -> go.Figure:
    """Daily closes over the detail page's selected range."""
    fig = go.Figure(
        _line(
            [str(point["date"]) for point in history],
            [float(point["close"]) for point in history],
            "Close",
            color=_PORTFOLIO_COLOR,
            area=True,
        )
    )
    return _style(fig, showlegend=False)


def growth_figure(result: dict[str, Any]) -> go.Figure:
    """Portfolio value over time, with the benchmark on the same months."""
    months = [str(point["date"]) for point in result["curve"]]
    fig = go.Figure(
        _line(
            months,
            [float(point["value"]) for point in result["curve"]],
            "Portfolio",
            color=_PORTFOLIO_COLOR,
            area=True,
        )
    )
    benchmarks = result.get("benchmarks") or (
        [result["benchmark"]] if result.get("benchmark") else []
    )
    for benchmark in benchmarks:
        by_month = {
            str(point["date"]): float(point["value"]) for point in benchmark["curve"]
        }
        fig.add_trace(
            _line(
                months,
                [by_month.get(month) for month in months],
                benchmark["symbol"],
                color=_BENCHMARK_COLOR,
                dash="dash",
            )
        )
    return _style(fig, showlegend=bool(benchmarks))
