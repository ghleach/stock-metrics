from __future__ import annotations

import pandas as pd

from stock_metrics.catalog import METRICS, Unit
from stock_metrics.charts import format_value, metric_chart, window
from stock_metrics.metrics import compute_metrics


def test_format_value() -> None:
    assert format_value(391_035_000_000, Unit.CURRENCY) == "$391.04B"
    assert format_value(-2_500_000, Unit.CURRENCY) == "-$2.5M"
    assert format_value(0.4623, Unit.PERCENT) == "46.2%"
    assert format_value(27.93, Unit.MULTIPLE) == "27.9x"
    assert format_value(15_116_786_000, Unit.COUNT) == "15.12B"
    assert format_value(float("nan"), Unit.RATIO) == "N/M"


def test_window() -> None:
    df = pd.DataFrame({"a": range(12)}, index=range(2014, 2026))
    assert list(window(df, 3).index) == [2023, 2024, 2025]
    assert len(window(df, None)) == 12


def test_every_metric_charts_without_error() -> None:
    base = pd.DataFrame(
        {
            "revenue": [100.0, 110.0, 121.0],
            "net_income": [10.0, 11.0, 12.0],
            "eps_diluted": [1.0, 1.1, 1.2],
            "price": [20.0, 22.0, 25.0],
        },
        index=[2021, 2022, 2023],
    )
    data = compute_metrics(base)
    for m in METRICS:
        fig = metric_chart(data, m.key)
        assert fig.data
