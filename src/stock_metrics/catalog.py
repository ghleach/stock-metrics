"""Catalogue of every metric the app shows: label, unit, dashboard tab and definition.

Keeping these in one place means the UI, exports and docs all agree on what a
metric means and how it is formatted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Unit(StrEnum):
    CURRENCY = "currency"  # USD, shown in $M / $B
    PER_SHARE = "per_share"  # USD per share
    COUNT = "count"  # share counts
    PERCENT = "percent"  # stored as a fraction (0.25 == 25%)
    MULTIPLE = "multiple"  # e.g. P/E 24.3x
    RATIO = "ratio"  # e.g. current ratio 1.4


class Tab(StrEnum):
    INCOME = "Financial Performance"
    MARGINS = "Profitability & Margins"
    VALUATION = "Valuation & Price Multiples"
    DIVIDENDS = "Dividends & Shareholder Returns"
    HEALTH = "Balance Sheet & Financial Health"


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    unit: Unit
    tab: Tab
    definition: str
    # Charts default to bars for absolute amounts and lines for ratios.
    default_chart: str = "line"


METRICS: tuple[MetricDef, ...] = (
    # --- Financial performance (income statement) ---
    MetricDef(
        "revenue",
        "Revenue",
        Unit.CURRENCY,
        Tab.INCOME,
        "Total revenue as reported in the 10-K.",
        "bar",
    ),
    MetricDef(
        "gross_profit",
        "Gross Profit",
        Unit.CURRENCY,
        Tab.INCOME,
        "Revenue minus cost of revenue.",
        "bar",
    ),
    MetricDef(
        "operating_income",
        "Operating Income (EBIT)",
        Unit.CURRENCY,
        Tab.INCOME,
        "Operating income as reported.",
        "bar",
    ),
    MetricDef(
        "ebitda",
        "EBITDA",
        Unit.CURRENCY,
        Tab.INCOME,
        "Operating income + depreciation & amortisation (cash flow statement).",
        "bar",
    ),
    MetricDef(
        "net_income",
        "Net Income",
        Unit.CURRENCY,
        Tab.INCOME,
        "Net income attributable to the company.",
        "bar",
    ),
    MetricDef(
        "free_cash_flow",
        "Free Cash Flow",
        Unit.CURRENCY,
        Tab.INCOME,
        "Operating cash flow minus capital expenditure.",
        "bar",
    ),
    MetricDef(
        "eps_diluted",
        "EPS (Diluted)",
        Unit.PER_SHARE,
        Tab.INCOME,
        "Diluted earnings per share, split-adjusted.",
        "bar",
    ),
    MetricDef(
        "eps_basic",
        "EPS (Basic)",
        Unit.PER_SHARE,
        Tab.INCOME,
        "Basic earnings per share, split-adjusted.",
        "bar",
    ),
    # --- Profitability & margins ---
    MetricDef("gross_margin", "Gross Margin", Unit.PERCENT, Tab.MARGINS, "Gross profit / revenue."),
    MetricDef(
        "operating_margin",
        "Operating Margin",
        Unit.PERCENT,
        Tab.MARGINS,
        "Operating income / revenue.",
    ),
    MetricDef("net_margin", "Net Margin", Unit.PERCENT, Tab.MARGINS, "Net income / revenue."),
    MetricDef(
        "roe",
        "Return on Equity (ROE)",
        Unit.PERCENT,
        Tab.MARGINS,
        "Net income / year-end shareholders' equity. N/M if equity is negative.",
    ),
    MetricDef(
        "roa",
        "Return on Assets (ROA)",
        Unit.PERCENT,
        Tab.MARGINS,
        "Net income / year-end total assets.",
    ),
    MetricDef(
        "roic",
        "Return on Invested Capital (ROIC)",
        Unit.PERCENT,
        Tab.MARGINS,
        "EBIT x (1 - effective tax rate) / (total debt + equity - cash). "
        "Tax rate falls back to 21% when it can't be calculated.",
    ),
    # --- Valuation ---
    MetricDef(
        "price",
        "Share Price (FY end)",
        Unit.PER_SHARE,
        Tab.VALUATION,
        "Closing price on the last trading day of the fiscal year, split-adjusted.",
    ),
    MetricDef(
        "market_cap",
        "Market Cap (FY end)",
        Unit.CURRENCY,
        Tab.VALUATION,
        "FY-end price x shares outstanding.",
        "bar",
    ),
    MetricDef(
        "pe",
        "P/E Ratio",
        Unit.MULTIPLE,
        Tab.VALUATION,
        "FY-end price / diluted EPS. N/M when EPS is zero or negative.",
    ),
    MetricDef("ps", "P/S Ratio", Unit.MULTIPLE, Tab.VALUATION, "Market cap / revenue."),
    MetricDef(
        "pb",
        "P/B Ratio",
        Unit.MULTIPLE,
        Tab.VALUATION,
        "Market cap / shareholders' equity. N/M when equity is negative.",
    ),
    MetricDef(
        "p_fcf",
        "Price / Free Cash Flow",
        Unit.MULTIPLE,
        Tab.VALUATION,
        "Market cap / free cash flow. N/M when FCF is zero or negative.",
    ),
    MetricDef(
        "peg",
        "PEG Ratio",
        Unit.MULTIPLE,
        Tab.VALUATION,
        "P/E / (3-year diluted EPS CAGR x 100). N/M when growth is zero or negative.",
    ),
    # --- Dividends & shareholder returns ---
    MetricDef(
        "dps",
        "Dividend per Share",
        Unit.PER_SHARE,
        Tab.DIVIDENDS,
        "Dividends declared per share in the fiscal year, split-adjusted.",
        "bar",
    ),
    MetricDef(
        "dividend_yield",
        "Dividend Yield",
        Unit.PERCENT,
        Tab.DIVIDENDS,
        "Dividend per share / FY-end price.",
    ),
    MetricDef(
        "payout_ratio",
        "Payout Ratio",
        Unit.PERCENT,
        Tab.DIVIDENDS,
        "Dividend per share / diluted EPS.",
    ),
    MetricDef(
        "shares_outstanding",
        "Shares Outstanding",
        Unit.COUNT,
        Tab.DIVIDENDS,
        "Shares outstanding at fiscal year end, split-adjusted (weighted-average diluted "
        "shares if the company doesn't report a total). "
        "Falling = buybacks, rising = dilution.",
        "bar",
    ),
    # --- Balance sheet & financial health ---
    MetricDef(
        "current_ratio",
        "Current Ratio",
        Unit.RATIO,
        Tab.HEALTH,
        "Current assets / current liabilities.",
    ),
    MetricDef(
        "quick_ratio",
        "Quick Ratio",
        Unit.RATIO,
        Tab.HEALTH,
        "(Cash + current marketable securities + receivables) / current liabilities.",
    ),
    MetricDef(
        "debt_to_equity",
        "Debt-to-Equity",
        Unit.RATIO,
        Tab.HEALTH,
        "Total borrowings (long-term debt incl. current portion + commercial paper "
        "+ short-term borrowings) / equity. N/M when equity is negative.",
    ),
    MetricDef(
        "total_debt",
        "Total Debt",
        Unit.CURRENCY,
        Tab.HEALTH,
        "Long-term debt incl. current portion + commercial paper + short-term borrowings.",
        "bar",
    ),
    MetricDef(
        "cash",
        "Cash & Equivalents",
        Unit.CURRENCY,
        Tab.HEALTH,
        "Cash and cash equivalents at year end.",
        "bar",
    ),
    MetricDef(
        "equity",
        "Shareholders' Equity",
        Unit.CURRENCY,
        Tab.HEALTH,
        "Total stockholders' equity at year end.",
        "bar",
    ),
)

METRICS_BY_KEY: dict[str, MetricDef] = {m.key: m for m in METRICS}


def metrics_for_tab(tab: Tab) -> list[MetricDef]:
    return [m for m in METRICS if m.tab == tab]
