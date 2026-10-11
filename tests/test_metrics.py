from __future__ import annotations

import math

import pandas as pd
import pytest

from stock_metrics.metrics import cagr, compute_metrics, series_cagr, yoy_growth


def base_frame(**cols: list[float]) -> pd.DataFrame:
    n = len(next(iter(cols.values())))
    return pd.DataFrame(cols, index=list(range(2020, 2020 + n)))


def test_cagr() -> None:
    assert cagr(100, 121, 2) == pytest.approx(0.10)
    assert math.isnan(cagr(-5, 10, 2))
    assert math.isnan(cagr(100, 120, 0))


def test_series_cagr_uses_first_and_last_available() -> None:
    s = pd.Series([float("nan"), 100.0, 110.0, 121.0], index=[2019, 2020, 2021, 2022])
    assert series_cagr(s) == pytest.approx(0.10)


def test_yoy_growth_from_loss() -> None:
    g = yoy_growth(pd.Series([-10.0, 5.0], index=[2020, 2021]))
    assert g.iloc[1] == pytest.approx(1.5)


def test_margins_and_returns() -> None:
    m = compute_metrics(
        base_frame(
            revenue=[200.0],
            cost_of_revenue=[120.0],
            operating_income=[40.0],
            net_income=[20.0],
            equity=[100.0],
            total_assets=[400.0],
        )
    )
    row = m.loc[2020]
    assert row["gross_profit"] == 80.0  # derived when GrossProfit isn't tagged
    assert row["gross_margin"] == pytest.approx(0.40)
    assert row["operating_margin"] == pytest.approx(0.20)
    assert row["net_margin"] == pytest.approx(0.10)
    assert row["roe"] == pytest.approx(0.20)
    assert row["roa"] == pytest.approx(0.05)


def test_valuation_is_nm_for_negative_earnings_and_equity() -> None:
    m = compute_metrics(
        base_frame(
            revenue=[100.0],
            eps_diluted=[-1.0],
            price=[50.0],
            shares_outstanding=[10.0],
            equity=[-5.0],
            net_income=[-10.0],
        )
    )
    row = m.loc[2020]
    assert row["market_cap"] == 500.0
    assert row["ps"] == pytest.approx(5.0)
    assert math.isnan(row["pe"])
    assert math.isnan(row["pb"])
    assert math.isnan(row["roe"])


def test_peg_uses_three_year_eps_cagr() -> None:
    m = compute_metrics(
        base_frame(
            eps_diluted=[1.0, 1.1, 1.21, 1.331],
            price=[13.31, 13.31, 13.31, 13.31],
        )
    )
    # P/E 10x, EPS CAGR 10% -> PEG 1.0
    assert m.loc[2023, "peg"] == pytest.approx(1.0)
    assert math.isnan(m.loc[2022, "peg"])  # not enough history


def test_debt_does_not_double_count_commercial_paper() -> None:
    m = compute_metrics(
        base_frame(
            lt_debt_noncurrent=[80.0],
            lt_debt_current=[20.0],
            commercial_paper=[10.0],
            short_term_borrowings=[15.0],
            equity=[50.0],
        )
    )
    # Short-term borrowings already include commercial paper.
    assert m.loc[2020, "total_debt"] == 115.0
    assert m.loc[2020, "debt_to_equity"] == pytest.approx(2.3)


def test_dividend_metrics_and_fcf() -> None:
    m = compute_metrics(
        base_frame(
            dps=[1.0],
            price=[50.0],
            eps_diluted=[4.0],
            operating_cash_flow=[30.0],
            capex=[10.0],
        )
    )
    assert m.loc[2020, "dividend_yield"] == pytest.approx(0.02)
    assert m.loc[2020, "payout_ratio"] == pytest.approx(0.25)
    assert m.loc[2020, "free_cash_flow"] == 20.0


def test_liquidity() -> None:
    m = compute_metrics(
        base_frame(
            current_assets=[150.0],
            current_liabilities=[100.0],
            cash=[30.0],
            marketable_securities=[20.0],
            receivables=[10.0],
        )
    )
    assert m.loc[2020, "current_ratio"] == pytest.approx(1.5)
    assert m.loc[2020, "quick_ratio"] == pytest.approx(0.6)
