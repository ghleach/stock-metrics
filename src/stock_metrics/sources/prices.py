"""Share prices, splits and dividends from Yahoo Finance (via yfinance).

Yahoo's `Close` (with auto_adjust=False) is split-adjusted but not
dividend-adjusted, which is what valuation ratios need. Dividends are
split-adjusted too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf


@dataclass(frozen=True)
class PriceHistory:
    close: pd.Series  # indexed by date, split-adjusted close
    splits: pd.Series  # indexed by date, ratio (e.g. 4.0 for a 4-for-1)
    dividends: pd.Series  # indexed by date, split-adjusted per-share amount


def _to_date_index(s: pd.Series) -> pd.Series:
    if s.empty:
        return pd.Series(dtype=float)
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out = pd.Series(s.to_numpy(dtype=float), index=idx.normalize())
    return out.sort_index()


def fetch_price_history(ticker: str) -> PriceHistory:
    t = yf.Ticker(ticker)
    hist = t.history(period="max", auto_adjust=False, actions=True)
    if hist.empty:
        return PriceHistory(pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float))
    close = _to_date_index(hist["Close"])
    splits = _to_date_index(hist["Stock Splits"])
    dividends = _to_date_index(hist["Dividends"])
    return PriceHistory(
        close=close,
        splits=splits[splits > 0],
        dividends=dividends[dividends > 0],
    )


def price_on_or_before(close: pd.Series, when: date) -> float | None:
    """Last close on or before `when` (fiscal years can end on a weekend)."""
    if close.empty:
        return None
    window = close.loc[: pd.Timestamp(when)]
    if window.empty or (pd.Timestamp(when) - window.index[-1]).days > 10:
        return None
    return float(window.iloc[-1])


def split_factor_after(splits: pd.Series, after: date) -> float:
    """Product of all split ratios strictly after `after`.

    A figure reported in a filing made on date F already reflects splits before
    F. Multiply share counts (or divide per-share amounts) by this factor to
    express it in today's share terms.
    """
    if splits.empty:
        return 1.0
    later = splits.loc[splits.index > pd.Timestamp(after)]
    return float(np.prod(later.to_numpy(dtype=float))) if not later.empty else 1.0


def dividends_between(dividends: pd.Series, start: date, end: date) -> float:
    """Sum of dividends with ex-date in (start, end]."""
    if dividends.empty:
        return 0.0
    mask = (dividends.index > pd.Timestamp(start)) & (dividends.index <= pd.Timestamp(end))
    return float(dividends.loc[mask].sum())


# US listings that represent more than one underlying share (ADRs). Filings report
# per underlying share; per-share figures are multiplied by this so they're per
# ADR, matching the US price. Ratios come from the depositary agreements.
SHARES_PER_LISTED_SHARE: dict[str, float] = {
    "KOF": 80.0,  # 1 ADS = 10 units; 1 unit = 3 Series B + 5 Series L shares
}


def fetch_fx_history(currency: str) -> pd.Series:
    """Daily USD value of one unit of `currency` (empty for USD)."""
    if currency.upper() == "USD":
        return pd.Series(dtype=float)
    hist = yf.Ticker(f"{currency.upper()}USD=X").history(period="max", auto_adjust=False)
    if hist.empty:
        return pd.Series(dtype=float)
    return _to_date_index(hist["Close"])


def fx_on_or_before(fx: pd.Series, when: date) -> float | None:
    """Exchange rate for balance-sheet figures (at the period end)."""
    return price_on_or_before(fx, when)


def fx_average(fx: pd.Series, start: date, end: date) -> float | None:
    """Average daily rate over (start, end], for income and cash-flow figures."""
    if fx.empty:
        return None
    window = fx.loc[(fx.index > pd.Timestamp(start)) & (fx.index <= pd.Timestamp(end))]
    if len(window) < 20:  # need most of the year to call it an average
        return None
    return float(window.mean())
