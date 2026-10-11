from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from stock_metrics.sources.prices import PriceHistory


def fact(
    val: float,
    end: str,
    filed: str,
    start: str | None = None,
    form: str = "10-K",
    accn: str = "0000000000-00-000001",
) -> dict[str, Any]:
    e: dict[str, Any] = {"val": val, "end": end, "filed": filed, "form": form, "accn": accn}
    if start:
        e["start"] = start
    return e


def company_facts(
    us_gaap: dict[str, dict[str, list[dict[str, Any]]]],
    dei: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
    ifrs: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    def wrap(tags: dict[str, dict[str, list[dict[str, Any]]]]) -> dict[str, Any]:
        return {tag: {"units": units} for tag, units in tags.items()}

    facts: dict[str, Any] = {"us-gaap": wrap(us_gaap)}
    if dei:
        facts["dei"] = wrap(dei)
    if ifrs:
        facts["ifrs-full"] = wrap(ifrs)
    return {"cik": 1, "entityName": "Test Co", "facts": facts}


@pytest.fixture
def sample_facts() -> dict[str, Any]:
    """Two fiscal years ending 30 Sep, with a revenue tag switch and a restatement."""
    return company_facts(
        {
            "SalesRevenueNet": {
                "USD": [
                    fact(100.0, "2022-09-30", "2022-11-01", start="2021-10-01"),
                ]
            },
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "USD": [
                    fact(120.0, "2023-09-30", "2023-11-01", start="2022-10-01"),
                    # A quarterly value inside a 10-K must be ignored.
                    fact(30.0, "2023-09-30", "2023-11-01", start="2023-07-01"),
                ]
            },
            "NetIncomeLoss": {
                "USD": [
                    fact(10.0, "2022-09-30", "2022-11-01", start="2021-10-01"),
                    fact(12.0, "2023-09-30", "2023-11-01", start="2022-10-01"),
                    # Restated in the next year's filing: latest filing wins.
                    fact(11.0, "2022-09-30", "2023-11-01", start="2021-10-01"),
                ]
            },
            "EarningsPerShareDiluted": {
                "USD/shares": [
                    fact(2.0, "2022-09-30", "2022-11-01", start="2021-10-01"),
                    fact(1.2, "2023-09-30", "2023-11-01", start="2022-10-01"),
                ]
            },
            "StockholdersEquity": {
                "USD": [
                    fact(50.0, "2022-09-30", "2022-11-01"),
                    fact(60.0, "2023-09-30", "2023-11-01"),
                    fact(55.0, "2023-06-30", "2023-08-01", form="10-Q"),
                ]
            },
        },
        dei={
            "EntityCommonStockSharesOutstanding": {
                "shares": [
                    fact(5.0, "2022-10-20", "2022-11-01"),
                    fact(10.0, "2023-10-20", "2023-11-01"),
                ]
            },
        },
    )


@pytest.fixture
def price_history() -> PriceHistory:
    """Daily closes over 2021-2023 with a 2-for-1 split on 2023-03-01."""
    idx = pd.bdate_range("2021-01-01", "2023-12-31")
    close = pd.Series(10.0, index=idx)
    splits = pd.Series([2.0], index=pd.DatetimeIndex(["2023-03-01"]))
    dividends = pd.Series(
        [0.1, 0.1, 0.1], index=pd.DatetimeIndex(["2022-02-01", "2022-08-01", "2023-02-01"])
    )
    return PriceHistory(close=close, splits=splits, dividends=dividends)
