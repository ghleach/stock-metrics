"""SEC EDGAR: ticker lookup and annual figures from XBRL "company facts".

Covers US filers (10-K, US-GAAP tags) and foreign private issuers listed in the
US (20-F/40-F, usually IFRS tags, often in a non-USD reporting currency).

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


MONEY = "money"  # reporting currency, e.g. USD or MXN
PER_SHARE = "per_share"  # reporting currency per share
SHARES = "shares"

# Annual report forms: US companies file 10-K; foreign private issuers file 20-F,
# and Canadian issuers can file 40-F. Amendments ("/A") and transition reports count too.
ANNUAL_FORMS = ("10-K", "20-F", "40-F")


@dataclass(frozen=True)
class Concept:
    """A base figure we pull from filings.

    `tags` are in priority order. Unprefixed tags are US-GAAP; IFRS tags (used by
    foreign filers) are prefixed "ifrs-full:" and cover-page tags "dei:".
    """

    key: str
    tags: tuple[str, ...]
    unit: str  # MONEY, PER_SHARE or SHARES
    instant: bool  # balance-sheet value at FY end vs. a flow over the year


CONCEPTS: tuple[Concept, ...] = (
    Concept(
        "revenue",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueGoodsNet",
            "ifrs-full:Revenue",
            "ifrs-full:RevenueFromContractsWithCustomers",
        ),
        MONEY,
        instant=False,
    ),
    Concept(
        "cost_of_revenue",
        (
            "CostOfRevenue",
            "CostOfGoodsAndServicesSold",
            "CostOfGoodsSold",
            "ifrs-full:CostOfSales",
        ),
        MONEY,
        instant=False,
    ),
    Concept("gross_profit", ("GrossProfit", "ifrs-full:GrossProfit"), MONEY, instant=False),
    Concept(
        "operating_income",
        ("OperatingIncomeLoss", "ifrs-full:ProfitLossFromOperatingActivities"),
        MONEY,
        instant=False,
    ),
    Concept(
        "net_income",
        (
            "NetIncomeLoss",
            "NetIncomeLossAvailableToCommonStockholdersBasic",
            "ProfitLoss",
            "ifrs-full:ProfitLossAttributableToOwnersOfParent",
            "ifrs-full:ProfitLoss",
        ),
        MONEY,
        instant=False,
    ),
    Concept(
        "pretax_income",
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
            "ifrs-full:ProfitLossBeforeTax",
        ),
        MONEY,
        instant=False,
    ),
    Concept(
        "income_tax",
        ("IncomeTaxExpenseBenefit", "ifrs-full:IncomeTaxExpenseContinuingOperations"),
        MONEY,
        instant=False,
    ),
    Concept(
        "d_and_a",
        (
            "DepreciationDepletionAndAmortization",
            "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization",
            "ifrs-full:DepreciationAndAmortisationExpense",
            "ifrs-full:AdjustmentsForDepreciationAndAmortisationExpense",
        ),
        MONEY,
        instant=False,
    ),
    Concept(
        "operating_cash_flow",
        (
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            "ifrs-full:CashFlowsFromUsedInOperatingActivities",
        ),
        MONEY,
        instant=False,
    ),
    Concept(
        "capex",
        (
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
            "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
            "ifrs-full:PurchaseOfPropertyPlantAndEquipment",
            "ifrs-full:PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets",
        ),
        MONEY,
        instant=False,
    ),
    Concept(
        "eps_basic",
        ("EarningsPerShareBasic", "ifrs-full:BasicEarningsLossPerShare"),
        PER_SHARE,
        instant=False,
    ),
    Concept(
        "eps_diluted",
        (
            "EarningsPerShareDiluted",
            "ifrs-full:DilutedEarningsLossPerShare",
            "ifrs-full:BasicAndDilutedEarningsLossPerShare",
        ),
        PER_SHARE,
        instant=False,
    ),
    Concept(
        "dps",
        (
            "CommonStockDividendsPerShareDeclared",
            "CommonStockDividendsPerShareCashPaid",
        ),
        PER_SHARE,
        instant=False,
    ),
    Concept(
        "shares_outstanding",
        ("CommonStockSharesOutstanding", "ifrs-full:NumberOfSharesOutstanding"),
        SHARES,
        instant=True,
    ),
    # Weighted-average diluted shares; last resort when no total share count is
    # tagged (e.g. companies that only report counts per share class).
    Concept(
        "diluted_shares_weighted",
        (
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "ifrs-full:AdjustedWeightedAverageShares",
            "ifrs-full:WeightedAverageShares",
        ),
        SHARES,
        instant=False,
    ),
    # Cover-page share count; used when the balance sheet doesn't tag one.
    Concept(
        "shares_outstanding_cover",
        ("dei:EntityCommonStockSharesOutstanding",),
        SHARES,
        instant=True,
    ),
    Concept(
        "equity",
        (
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            "ifrs-full:EquityAttributableToOwnersOfParent",
            "ifrs-full:Equity",
        ),
        MONEY,
        instant=True,
    ),
    Concept("total_assets", ("Assets", "ifrs-full:Assets"), MONEY, instant=True),
    Concept("current_assets", ("AssetsCurrent", "ifrs-full:CurrentAssets"), MONEY, instant=True),
    Concept(
        "current_liabilities",
        ("LiabilitiesCurrent", "ifrs-full:CurrentLiabilities"),
        MONEY,
        instant=True,
    ),
    Concept(
        "cash",
        (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "ifrs-full:CashAndCashEquivalents",
        ),
        MONEY,
        instant=True,
    ),
    Concept(
        "marketable_securities",
        (
            "MarketableSecuritiesCurrent",
            "ShortTermInvestments",
            "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
            "ifrs-full:CurrentFinancialAssetsAtFairValueThroughProfitOrLoss",
            "ifrs-full:OtherCurrentFinancialAssets",
        ),
        MONEY,
        instant=True,
    ),
    Concept(
        "receivables",
        (
            "AccountsReceivableNetCurrent",
            "ReceivablesNetCurrent",
            "ifrs-full:TradeAndOtherCurrentReceivables",
        ),
        MONEY,
        instant=True,
    ),
    Concept(
        "lt_debt_total",
        (
            "LongTermDebt",
            "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        ),
        MONEY,
        instant=True,
    ),
    # IFRS "LongtermBorrowings" is the non-current portion; its current portion is
    # tagged separately, and short-term borrowings separately again.
    Concept(
        "lt_debt_noncurrent",
        (
            "LongTermDebtNoncurrent",
            "LongTermDebtAndCapitalLeaseObligations",
            "ifrs-full:LongtermBorrowings",
        ),
        MONEY,
        instant=True,
    ),
    Concept(
        "lt_debt_current",
        (
            "LongTermDebtCurrent",
            "LongTermDebtAndCapitalLeaseObligationsCurrent",
            "ifrs-full:CurrentPortionOfLongtermBorrowings",
        ),
        MONEY,
        instant=True,
    ),
    Concept("commercial_paper", ("CommercialPaper",), MONEY, instant=True),
    Concept(
        "short_term_borrowings",
        ("ShortTermBorrowings", "ifrs-full:ShorttermBorrowings"),
        MONEY,
        instant=True,
    ),
)

CONCEPTS_BY_KEY: dict[str, Concept] = {c.key: c for c in CONCEPTS}

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


def _split_tag(tag: str) -> tuple[str, str]:
    taxonomy, _, name = tag.rpartition(":")
    return (taxonomy or "us-gaap"), name


def _unit_key(concept: Concept, currency: str) -> str:
    if concept.unit == MONEY:
        return currency
    if concept.unit == PER_SHARE:
        return f"{currency}/shares"
    return "shares"


def reporting_currency(facts: dict[str, Any]) -> str:
    """The currency the company reports in, judged from its annual revenue/net income.

    Some foreign filers also tag a USD "convenience translation" of the latest
    year, so count every annual fact rather than taking the first unit seen.
    """
    counts: dict[str, int] = {}
    for key in _ANCHOR_CONCEPTS:
        for tag in CONCEPTS_BY_KEY[key].tags:
            taxonomy, name = _split_tag(tag)
            node = facts.get("facts", {}).get(taxonomy, {}).get(name, {})
            for unit, entries in node.get("units", {}).items():
                if "/" in unit:
                    continue
                n = sum(1 for e in entries if str(e.get("form", "")).startswith(ANNUAL_FORMS))
                counts[unit] = counts.get(unit, 0) + n
    return max(counts, key=lambda u: counts[u]) if counts else "USD"


def _annual_entries(
    facts: dict[str, Any], concept: Concept, tag: str, currency: str
) -> list[dict[str, Any]]:
    taxonomy, name = _split_tag(tag)
    node = facts.get("facts", {}).get(taxonomy, {}).get(name)
    if not node:
        return []
    entries: list[dict[str, Any]] = node.get("units", {}).get(_unit_key(concept, currency), [])
    out = []
    for e in entries:
        if not str(e.get("form", "")).startswith(ANNUAL_FORMS):
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


def fiscal_year_ends(facts: dict[str, Any], currency: str | None = None) -> list[date]:
    """Distinct fiscal-year end dates, discovered from annual revenue/net income."""
    currency = currency or reporting_currency(facts)
    ends: set[date] = set()
    for key in _ANCHOR_CONCEPTS:
        concept = CONCEPTS_BY_KEY[key]
        for tag in concept.tags:
            ends.update(
                date.fromisoformat(e["end"]) for e in _annual_entries(facts, concept, tag, currency)
            )
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
    counts are dated weeks or months after year end (foreign filers' 20-Fs come
    later than 10-Ks), so take the latest FY end within 200 days before them.
    """
    if not cover:
        return entry_end if entry_end in fy_ends else None
    candidates = [e for e in fy_ends if 0 <= (entry_end - e).days <= 200]
    return max(candidates) if candidates else None


def extract_annual_facts(facts: dict[str, Any], currency: str | None = None) -> list[AnnualFact]:
    """Resolve every base concept to at most one value per fiscal year.

    For each year the first tag in the concept's priority list that has a value
    wins; among that tag's values the most recently filed one wins, so later
    restatements replace originally reported numbers. Values stay in the
    company's reporting currency (see `reporting_currency`).
    """
    currency = currency or reporting_currency(facts)
    fy_ends = set(fiscal_year_ends(facts, currency))
    results: list[AnnualFact] = []
    for concept in CONCEPTS:
        chosen: dict[date, AnnualFact] = {}
        for tag in concept.tags:
            taxonomy, name = _split_tag(tag)
            best_for_tag: dict[date, AnnualFact] = {}
            for e in _annual_entries(facts, concept, tag, currency):
                period_end = _match_period_end(
                    date.fromisoformat(e["end"]), fy_ends, cover=taxonomy == "dei"
                )
                if period_end is None or period_end in chosen:
                    continue
                fact = AnnualFact(
                    concept=concept.key,
                    fiscal_year=fiscal_year_for(period_end),
                    period_end=period_end,
                    value=float(e["val"]),
                    tag=f"{taxonomy}:{name}",
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
