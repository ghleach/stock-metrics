"""Derived metrics, calculated from base figures.

Everything here is a pure function of a DataFrame indexed by fiscal year whose
columns are base concepts (see `sources.edgar.CONCEPTS`, plus `price`). Base
figures are already split-adjusted and have manual overrides applied.

Ratios that are meaningless (for example P/E with negative earnings) are NaN,
which the UI shows as "N/M".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_TAX_RATE = 0.21


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df.columns:
        return df[name].astype(float)
    return pd.Series(np.nan, index=df.index, dtype=float)


def _div(num: pd.Series, den: pd.Series, positive_den: bool = True) -> pd.Series:
    """num / den, NaN where the denominator is zero (or not positive)."""
    bad = den <= 0 if positive_den else den == 0
    return (num / den.mask(bad)).astype(float)


def _first_available(*series: pd.Series) -> pd.Series:
    out = series[0].copy()
    for s in series[1:]:
        out = out.fillna(s)
    return out


def cagr(start: float, end: float, years: float) -> float:
    """Compound annual growth rate; NaN if either end is not positive."""
    if years <= 0 or not np.isfinite(start) or not np.isfinite(end) or start <= 0 or end <= 0:
        return float("nan")
    return float((end / start) ** (1.0 / years) - 1.0)


def yoy_growth(s: pd.Series) -> pd.Series:
    """Year-over-year change. Uses |previous| so growth from a loss reads sensibly."""
    prev = s.shift(1)
    return ((s - prev) / prev.abs().mask(prev == 0)).astype(float)


def series_cagr(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 2:
        return float("nan")
    years = float(s.index[-1] - s.index[0])
    return cagr(float(s.iloc[0]), float(s.iloc[-1]), years)


def compute_metrics(base: pd.DataFrame) -> pd.DataFrame:
    b = base.sort_index()
    out = pd.DataFrame(index=b.index)

    revenue = _col(b, "revenue")
    net_income = _col(b, "net_income")
    operating_income = _col(b, "operating_income")
    equity = _col(b, "equity")
    price = _col(b, "price")

    # --- Income statement ---
    out["revenue"] = revenue
    out["gross_profit"] = _first_available(
        _col(b, "gross_profit"), revenue - _col(b, "cost_of_revenue")
    )
    out["operating_income"] = operating_income
    out["ebitda"] = operating_income + _col(b, "d_and_a")
    out["net_income"] = net_income
    out["free_cash_flow"] = _col(b, "operating_cash_flow") - _col(b, "capex").fillna(0)
    out["eps_diluted"] = _first_available(_col(b, "eps_diluted"), _col(b, "eps_basic"))
    out["eps_basic"] = _col(b, "eps_basic")

    # --- Shares ---
    shares = _first_available(
        _col(b, "shares_outstanding"),
        _col(b, "shares_outstanding_cover"),
        _col(b, "diluted_shares_weighted"),
    )
    out["shares_outstanding"] = shares

    # --- Margins & returns ---
    out["gross_margin"] = _div(out["gross_profit"], revenue)
    out["operating_margin"] = _div(operating_income, revenue)
    out["net_margin"] = _div(net_income, revenue)
    out["roe"] = _div(net_income, equity)
    out["roa"] = _div(net_income, _col(b, "total_assets"))

    # Debt: long-term debt including current portion, plus short-term borrowings.
    # ShortTermBorrowings usually already includes commercial paper, so use
    # whichever is reported rather than adding both.
    lt_debt = _first_available(
        _col(b, "lt_debt_total"),
        _col(b, "lt_debt_noncurrent") + _col(b, "lt_debt_current").fillna(0),
    )
    st_debt = _first_available(_col(b, "short_term_borrowings"), _col(b, "commercial_paper"))
    total_debt = lt_debt.fillna(0) + st_debt.fillna(0)
    total_debt = total_debt.mask(lt_debt.isna() & st_debt.isna())
    cash = _col(b, "cash")
    out["total_debt"] = total_debt
    out["cash"] = cash
    out["equity"] = equity

    pretax = _col(b, "pretax_income")
    tax_rate = _div(_col(b, "income_tax"), pretax).clip(0, 0.5).fillna(DEFAULT_TAX_RATE)
    invested_capital = total_debt.fillna(0) + equity - cash.fillna(0)
    out["roic"] = _div(operating_income * (1 - tax_rate), invested_capital)

    # --- Valuation ---
    market_cap = price * shares
    out["price"] = price
    out["market_cap"] = market_cap
    out["pe"] = _div(price, out["eps_diluted"])
    out["ps"] = _div(market_cap, revenue)
    out["pb"] = _div(market_cap, equity)
    out["p_fcf"] = _div(market_cap, out["free_cash_flow"])

    eps = out["eps_diluted"]
    eps_3y_cagr = pd.Series(
        [cagr(float(eps.get(fy - 3, np.nan)), float(eps.get(fy, np.nan)), 3) for fy in out.index],
        index=out.index,
        dtype=float,
    )
    out["peg"] = _div(out["pe"], eps_3y_cagr * 100)

    # --- Dividends ---
    dps = _col(b, "dps")
    out["dps"] = dps
    out["dividend_yield"] = _div(dps, price)
    out["payout_ratio"] = _div(dps, eps)

    # --- Liquidity & solvency ---
    current_liabilities = _col(b, "current_liabilities")
    out["current_ratio"] = _div(_col(b, "current_assets"), current_liabilities)
    quick_assets = (
        cash.fillna(0)
        + _col(b, "marketable_securities").fillna(0)
        + _col(b, "receivables").fillna(0)
    )
    out["quick_ratio"] = _div(quick_assets.mask(cash.isna()), current_liabilities)
    out["debt_to_equity"] = _div(total_debt, equity)

    return out
