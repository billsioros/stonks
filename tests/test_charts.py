"""Tests for the shared interactive chart figures."""

from stonks.charts import growth_figure, price_history_figure


def test_price_history_figure_uses_dates_and_closes() -> None:
    history = [
        {"date": "2025-01-01", "close": 100.0},
        {"date": "2025-02-01", "close": 110.0},
    ]

    fig = price_history_figure(history)

    assert len(fig.data) == 1
    assert list(fig.data[0].x) == ["2025-01-01", "2025-02-01"]
    assert list(fig.data[0].y) == [100.0, 110.0]
    assert fig.data[0].fill == "tozeroy"
    assert fig.layout.showlegend is False


def test_growth_figure_aligns_benchmark_to_portfolio_months() -> None:
    result = {
        "curve": [
            {"date": "2025-01", "value": 100.0},
            {"date": "2025-02", "value": 110.0},
            {"date": "2025-03", "value": 120.0},
        ],
        "benchmark": {
            "symbol": "VOO",
            "curve": [
                {"date": "2025-01", "value": 100.0},
                {"date": "2025-03", "value": 105.0},
            ],
        },
    }

    fig = growth_figure(result)

    assert [trace.name for trace in fig.data] == ["Portfolio", "VOO"]
    assert list(fig.data[1].x) == ["2025-01", "2025-02", "2025-03"]
    assert list(fig.data[1].y) == [100.0, None, 105.0]
    assert fig.data[1].line.dash == "dash"
    assert fig.layout.showlegend is True
