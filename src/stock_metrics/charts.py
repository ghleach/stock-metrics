"""Number formatting and Plotly figure builders used by the dashboard."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from stock_metrics.catalog import METRICS_BY_KEY, MetricDef, Unit
from stock_metrics.metrics import series_cagr, yoy_growth

# Colour-blind-safe categorical palette (Okabe-Ito order, minus yellow).
PALETTE = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9"]
GROWTH_UNITS = {Unit.CURRENCY, Unit.PER_SHARE, Unit.COUNT}


def _is_missing(v: float | None) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def format_value(v: float | None, unit: Unit) -> str:
    if _is_missing(v):
        return "N/M"
    assert v is not None
    if unit is Unit.CURRENCY:
        a = abs(v)
        sign = "-" if v < 0 else ""
        if a >= 1e12:
            return f"{sign}${a / 1e12:,.2f}T"
        if a >= 1e9:
            return f"{sign}${a / 1e9:,.2f}B"
        if a >= 1e6:
            return f"{sign}${a / 1e6:,.1f}M"
        return f"{sign}${a:,.0f}"
    if unit is Unit.PER_SHARE:
        sign = "-" if v < 0 else ""
        a = abs(v)
        # Tiny split-adjusted amounts (e.g. NVIDIA's early dividends) need more decimals.
        return f"{sign}${a:,.4f}" if 0 < a < 0.1 else f"{sign}${a:,.2f}"
    if unit is Unit.COUNT:
        return f"{v / 1e9:,.2f}B" if abs(v) >= 1e9 else f"{v / 1e6:,.1f}M"
    if unit is Unit.PERCENT:
        return f"{v * 100:,.1f}%"
    if unit is Unit.MULTIPLE:
        return f"{v:,.1f}x"
    return f"{v:,.2f}"


def format_pct(v: float | None) -> str:
    return "–" if _is_missing(v) else f"{v * 100:+.1f}%"  # type: ignore[operator]


def window(df: pd.DataFrame, years: int | None) -> pd.DataFrame:
    """Last `years` fiscal years (None = all)."""
    if df.empty or years is None:
        return df
    result: pd.DataFrame = df[df.index > df.index.max() - years]
    return result


def _axis_format(unit: Unit) -> dict[str, str]:
    if unit is Unit.PERCENT:
        return {"tickformat": ".0%"}
    if unit is Unit.CURRENCY:
        return {"tickprefix": "$", "tickformat": "~s"}
    if unit is Unit.PER_SHARE:
        return {"tickprefix": "$"}
    if unit is Unit.COUNT:
        return {"tickformat": "~s"}
    if unit is Unit.MULTIPLE:
        return {"ticksuffix": "x"}
    return {}


def subtitle(series: pd.Series, metric: MetricDef) -> str:
    s = series.dropna()
    if s.empty:
        return "No data"
    latest = f"FY{int(s.index[-1])}: {format_value(float(s.iloc[-1]), metric.unit)}"
    if metric.unit in GROWTH_UNITS:
        g = series_cagr(s)
        if not _is_missing(g):
            years = int(s.index[-1] - s.index[0])
            return f"{latest} · {years}-yr CAGR {format_pct(g)}"
        return latest
    return f"{latest} · avg {format_value(float(s.mean()), metric.unit)}"


def _layout(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(
        height=height,
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        xaxis={"dtick": 1, "tickformat": "d", "title": None},
        plot_bgcolor="rgba(0,0,0,0)",
        bargap=0.25,
    )
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.2)", zerolinecolor="rgba(128,128,128,0.5)")
    return fig


def _hover_text(series: pd.Series, unit: Unit) -> list[str]:
    yoy = yoy_growth(series)
    return [
        f"{format_value(v, unit)} (YoY {format_pct(g)})"
        for v, g in zip(series.tolist(), yoy.tolist(), strict=True)
    ]


def metric_chart(
    data: pd.DataFrame,
    key: str,
    chart_type: str = "auto",
    show_trend: bool = True,
    show_band: bool = True,
) -> go.Figure:
    """Time series for one metric, with CAGR trendline or average band."""
    metric = METRICS_BY_KEY[key]
    series = data[key] if key in data.columns else pd.Series(dtype=float)
    kind = metric.default_chart if chart_type == "auto" else chart_type
    x = series.index.astype(int)
    hover = _hover_text(series, metric.unit)

    fig = go.Figure()
    if kind == "bar":
        fig.add_bar(
            x=x,
            y=series,
            name=metric.label,
            marker_color=PALETTE[0],
            customdata=hover,
            hovertemplate="%{customdata}<extra></extra>",
        )
    else:
        fig.add_scatter(
            x=x,
            y=series,
            name=metric.label,
            mode="lines+markers",
            line={"color": PALETTE[0], "width": 2.5},
            customdata=hover,
            hovertemplate="%{customdata}<extra></extra>",
        )

    s = series.dropna()
    if show_trend and metric.unit in GROWTH_UNITS and len(s) >= 3:
        g = series_cagr(s)
        if not _is_missing(g):
            years = s.index - s.index[0]
            trend = float(s.iloc[0]) * (1 + g) ** years
            fig.add_scatter(
                x=s.index.astype(int),
                y=trend,
                name=f"CAGR {format_pct(g)}",
                mode="lines",
                line={"color": PALETTE[1], "dash": "dash", "width": 2},
                hoverinfo="skip",
            )
    if show_band and metric.unit is Unit.MULTIPLE and len(s) >= 3:
        mean, std = float(s.mean()), float(s.std())
        xs = list(s.index.astype(int))
        fig.add_scatter(
            x=xs + xs[::-1],
            y=[mean + std] * len(xs) + [mean - std] * len(xs),
            fill="toself",
            fillcolor="rgba(230,159,0,0.12)",
            line={"width": 0},
            name="±1 std dev",
            hoverinfo="skip",
        )
        fig.add_scatter(
            x=xs,
            y=[mean] * len(xs),
            mode="lines",
            name=f"Avg {mean:.1f}x",
            line={"color": PALETTE[1], "dash": "dot", "width": 2},
            hoverinfo="skip",
        )

    fig.update_yaxes(**_axis_format(metric.unit))
    _layout(fig)
    fig.update_layout(showlegend=len(fig.data) > 1)
    return fig


def dual_axis_chart(data: pd.DataFrame, left: str, right: str) -> go.Figure:
    """Two metrics on independent Y axes (e.g. Shares Outstanding vs EPS)."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    for i, (key, secondary) in enumerate(((left, False), (right, True))):
        metric = METRICS_BY_KEY[key]
        series = data[key] if key in data.columns else pd.Series(dtype=float)
        hover = _hover_text(series, metric.unit)
        common = {
            "x": series.index.astype(int),
            "y": series,
            "name": metric.label,
            "customdata": hover,
            "hovertemplate": "%{customdata}",
        }
        if metric.default_chart == "bar" and not secondary:
            trace: go.Bar | go.Scatter = go.Bar(marker_color=PALETTE[i], **common)
        else:
            trace = go.Scatter(
                mode="lines+markers", line={"color": PALETTE[i], "width": 2.5}, **common
            )
        fig.add_trace(trace, secondary_y=secondary)
        fig.update_yaxes(
            title_text=metric.label, secondary_y=secondary, **_axis_format(metric.unit)
        )
    fig.update_yaxes(showgrid=False, secondary_y=True)
    return _layout(fig, height=420)


def margin_overlay_chart(data: pd.DataFrame) -> go.Figure:
    """Revenue and profit bars with their margins as lines on a second axis."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    x = data.index.astype(int)
    bars = [
        ("revenue", None),
        ("gross_profit", "gross_margin"),
        ("operating_income", "operating_margin"),
        ("net_income", "net_margin"),
    ]
    for i, (amount, margin) in enumerate(bars):
        m = METRICS_BY_KEY[amount]
        fig.add_trace(
            go.Bar(
                x=x,
                y=data.get(amount),
                name=m.label,
                marker_color=PALETTE[i],
                customdata=_hover_text(data[amount], m.unit),
                hovertemplate="%{customdata}",
            ),
            secondary_y=False,
        )
        if margin:
            mm = METRICS_BY_KEY[margin]
            fig.add_trace(
                go.Scatter(
                    x=x,
                    y=data.get(margin),
                    name=mm.label,
                    mode="lines+markers",
                    line={"color": PALETTE[i], "dash": "dot", "width": 2},
                    hovertemplate="%{y:.1%}",
                ),
                secondary_y=True,
            )
    fig.update_yaxes(secondary_y=False, **_axis_format(Unit.CURRENCY))
    fig.update_yaxes(
        secondary_y=True, showgrid=False, rangemode="tozero", **_axis_format(Unit.PERCENT)
    )
    fig.update_layout(barmode="group")
    return _layout(fig, height=440)


def index_to_100(series: pd.Series) -> pd.Series:
    """Rebase a series so its first available value is 100.

    Returns all-NaN if the base value isn't positive (indexing from a loss is meaningless).
    """
    s = series.dropna()
    if s.empty or float(s.iloc[0]) <= 0:
        return pd.Series(np.nan, index=series.index, dtype=float)
    return (series / float(s.iloc[0]) * 100).astype(float)


def peer_chart(
    series_by_ticker: dict[str, pd.Series],
    key: str,
    indexed: bool = False,
    chart_type: str = "line",
) -> go.Figure:
    """One metric for several companies, raw or indexed to 100 at the first year shown."""
    metric = METRICS_BY_KEY[key]
    fig = go.Figure()
    for i, (ticker, series) in enumerate(series_by_ticker.items()):
        color = PALETTE[i % len(PALETTE)]
        y = index_to_100(series) if indexed else series
        hover = [
            f"{ticker}: {format_value(v, metric.unit)}"
            + (f" (index {iv:.0f})" if indexed and not _is_missing(iv) else "")
            + f" · YoY {format_pct(g)}"
            for v, iv, g in zip(
                series.tolist(), y.tolist(), yoy_growth(series).tolist(), strict=True
            )
        ]
        common = {
            "x": series.index.astype(int),
            "y": y,
            "name": ticker,
            "customdata": hover,
            "hovertemplate": "%{customdata}<extra></extra>",
        }
        if chart_type == "bar":
            fig.add_bar(marker_color=color, **common)
        else:
            fig.add_scatter(mode="lines+markers", line={"color": color, "width": 2.5}, **common)
    if indexed:
        fig.add_hline(y=100, line={"color": "rgba(128,128,128,0.6)", "dash": "dot", "width": 1})
        fig.update_yaxes(title_text="Index (first year = 100)")
    else:
        fig.update_yaxes(**_axis_format(metric.unit))
    fig.update_layout(barmode="group")
    return _layout(fig, height=440)


def formatted_table(data: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Metrics as rows, fiscal years as columns, values formatted for display."""
    rows = {}
    for key in keys:
        if key not in data.columns:
            continue
        unit = METRICS_BY_KEY[key].unit
        rows[METRICS_BY_KEY[key].label] = [format_value(v, unit) for v in data[key].tolist()]
    table = pd.DataFrame(rows, index=[f"FY{int(y)}" for y in data.index]).T
    return table.replace({np.nan: "N/M"})
