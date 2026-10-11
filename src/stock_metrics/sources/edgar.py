"""SEC EDGAR: ticker lookup and annual figures from XBRL "company facts".

Companies label the same figure with different US-GAAP tags, and sometimes
switch tags between years (Apple moved from SalesRevenueNet to
RevenueFromContractWithCustomerExcludingAssessedTax in 2018). Each base
concept therefore has a priority list of tags, resolved per fiscal year.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Annual periods are ~52/53 weeks; allow some slack for odd calendars.
MIN_ANNUAL_DAYS = 340
MAX_ANNUAL_DAYS = 390


@dataclass(frozen=True)
class Concept:
    """A base figure we pull from filings."""

    key: str
    tags: tuple[str, ...]
    unit: str  # "USD", "USD/shares" or "shares"
    instant: bool  # balance-sheet value at FY end vs. a flow over the year
    taxonomy: str = "us-gaap"


CONCEPTS: tuple[Concept, ...] = (
    Concept(
        "revenue",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueGoodsNet",
        ),
        "USD",
        instant=False,
    ),
    Concept(
        "cost_of_revenue",
        (
            "CostOfRevenue",
            "CostOfGoodsAndServicesSold",
            "CostOfGoodsSold",
        ),
        "USD",
        instant=False,
    ),
    Concept("gross_profit", ("GrossProfit",), "USD", instant=False),
    Concept("operating_income", ("OperatingIncomeLoss",), "USD", instant=False),
    Concept(
        "net_income",
        (
            "NetIncomeLoss",
            "NetIncomeLossAvailableToCommonStockholdersBasic",
            "ProfitLoss",
        ),
        "USD",
        instant=False,
    ),
    Concept(
        "pretax_income",
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
        ),
        "USD",
        instant=False,
    ),
    Concept("income_tax", ("IncomeTaxExpenseBenefit",), "USD", instant=False),
    Concept(
        "d_and_a",
        (
            "DepreciationDepletionAndAmortization",
            "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization",
        ),
        "USD",
        instant=False,
    ),
    Concept(
        "operating_cash_flow",
        (
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ),
        "USD",
        instant=False,
    ),
    Concept(
        "capex",
        (
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
        ),
        "USD",
        instant=False,
    ),
    Concept("eps_basic", ("EarningsPerShareBasic",), "USD/shares", instant=False),
    Concept("eps_diluted", ("EarningsPerShareDiluted",), "USD/shares", instant=False),
    Concept(
        "dps",
        (
            "CommonStockDividendsPerShareDeclared",
            "CommonStockDividendsPerShareCashPaid",
        ),
        "USD/shares",
        instant=False,
    ),
    Concept("shares_outstanding", ("CommonStockSharesOutstanding",), "shares", instant=True),
    # Cover-page share count; used when the balance sheet doesn't tag one.
    Concept(
        "shares_outstanding_cover",
        ("EntityCommonStockSharesOutstanding",),
        "shares",
        instant=True,
        taxonomy="dei",
    ),
    Concept(
        "equity",
        (
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        "USD",
        instant=True,
    ),
    Concept("total_assets", ("Assets",), "USD", instant=True),
    Concept("current_assets", ("AssetsCurrent",), "USD", instant=True),
    Concept("current_liabilities", ("LiabilitiesCurrent",), "USD", instant=True),
    Concept(
        "cash",
        (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ),
        "USD",
        instant=True,
    ),
    Concept(
        "marketable_securities",
        (
            "MarketableSecuritiesCurrent",
            "ShortTermInvestments",
            "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
        ),
        "USD",
        instant=True,
    ),
    Concept(
        "receivables",
        (
            "AccountsReceivableNetCurrent",
            "ReceivablesNetCurrent",
        ),
        "USD",
        instant=True,
    ),
    Concept(
        "lt_debt_total",
        (
            "LongTermDebt",
            "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        ),
        "USD",
        instant=True,
    ),
    Concept(
        "lt_debt_noncurrent",
        (
            "LongTermDebtNoncurrent",
            "LongTermDebtAndCapitalLeaseObligations",
        ),
        "USD",
        instant=True,
    ),
    Concept(
        "lt_debt_current",
        (
            "LongTermDebtCurrent",
            "LongTermDebtAndCapitalLeaseObligationsCurrent",
        ),
        "USD",
        instant=True,
    ),
    Concept("commercial_paper", ("CommercialPaper",), "USD", instant=True),
    Concept("short_term_borrowings", ("ShortTermBorrowings",), "USD", instant=True),
)

# Tags used to discover the company's fiscal year end dates.
_ANCHOR_CONCEPTS = ("revenue", "net_income")


@dataclass(frozen=True)
class SecCompany:
    ticker: str
    cik: int
    name: str


@dataclass(frozen=True)
class AnnualFact:
    """One base figure for one fiscal year, with where it came from."""

    concept: str
    fiscal_year: int
    period_end: date
    value: float
    tag: str
    accn: str
    filed: date
    form: str


class EdgarClient:
    def __init__(self, user_agent: str, timeout: float = 30.0) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip"})
        self._timeout = timeout

    def _get_json(self, url: str) -> Any:
        resp = self._session.get(url, timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()

    def ticker_list(self) -> list[SecCompany]:
        data = self._get_json(TICKERS_URL)
        return [
            SecCompany(ticker=row["ticker"].upper(), cik=int(row["cik_str"]), name=row["title"])
            for row in data.values()
        ]

    def company_facts(self, cik: int) -> dict[str, Any]:
        result: dict[str, Any] = self._get_json(FACTS_URL.format(cik=cik))
        return result


def fiscal_year_for(end: date) -> int:
    """Label a fiscal year by the calendar year it ends in.

    52/53-week years that spill a few days into January belong to the prior year.
    """
    if end.month == 1 and end.day <= 7:
        return end.year - 1
    return end.year


def _annual_entries(facts: dict[str, Any], concept: Concept, tag: str) -> list[dict[str, Any]]:
    node = facts.get("facts", {}).get(concept.taxonomy, {}).get(tag)
    if not node:
        return []
    entries: list[dict[str, Any]] = node.get("units", {}).get(concept.unit, [])
    out = []
    for e in entries:
        if not str(e.get("form", "")).startswith("10-K"):
            continue
        if not concept.instant:
            start = date.fromisoformat(e["start"]) if "start" in e else None
            if start is None:
                continue
            days = (date.fromisoformat(e["end"]) - start).days
            if not MIN_ANNUAL_DAYS <= days <= MAX_ANNUAL_DAYS:
                continue
        out.append(e)
    return out


def fiscal_year_ends(facts: dict[str, Any]) -> list[date]:
    """Distinct fiscal-year end dates, discovered from annual revenue/net income."""
    ends: set[date] = set()
    for concept in CONCEPTS:
        if concept.key not in _ANCHOR_CONCEPTS:
            continue
        for tag in concept.tags:
            ends.update(date.fromisoformat(e["end"]) for e in _annual_entries(facts, concept, tag))
    # Keep the latest end date per fiscal-year label (guards against odd stubs).
    by_year: dict[int, date] = {}
    for end in ends:
        fy = fiscal_year_for(end)
        if fy not in by_year or end > by_year[fy]:
            by_year[fy] = end
    return sorted(by_year.values())


def _match_period_end(entry_end: date, fy_ends: Iterable[date], cover: bool) -> date | None:
    """Which fiscal-year end does a fact belong to?

    Statement facts must end exactly on a fiscal-year end. Cover-page share
    counts are dated a few weeks after year end, so take the latest FY end
    within 120 days before them.
    """
    if not cover:
        return entry_end if entry_end in fy_ends else None
    candidates = [e for e in fy_ends if 0 <= (entry_end - e).days <= 120]
    return max(candidates) if candidates else None


def extract_annual_facts(facts: dict[str, Any]) -> list[AnnualFact]:
    """Resolve every base concept to at most one value per fiscal year.

    For each year the first tag in the concept's priority list that has a value
    wins; among that tag's values the most recently filed one wins, so later
    restatements replace originally reported numbers.
    """
    fy_ends = set(fiscal_year_ends(facts))
    results: list[AnnualFact] = []
    for concept in CONCEPTS:
        chosen: dict[date, AnnualFact] = {}
        for tag in concept.tags:
            best_for_tag: dict[date, AnnualFact] = {}
            for e in _annual_entries(facts, concept, tag):
                period_end = _match_period_end(
                    date.fromisoformat(e["end"]), fy_ends, cover=concept.taxonomy == "dei"
                )
                if period_end is None or period_end in chosen:
                    continue
                fact = AnnualFact(
                    concept=concept.key,
                    fiscal_year=fiscal_year_for(period_end),
                    period_end=period_end,
                    value=float(e["val"]),
                    tag=f"{concept.taxonomy}:{tag}",
                    accn=e.get("accn", ""),
                    filed=date.fromisoformat(e["filed"]),
                    form=e.get("form", ""),
                )
                current = best_for_tag.get(period_end)
                if current is None or fact.filed > current.filed:
                    best_for_tag[period_end] = fact
            chosen.update(best_for_tag)
        results.extend(chosen.values())
    return results
