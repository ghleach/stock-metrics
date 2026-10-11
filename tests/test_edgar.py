from __future__ import annotations

from datetime import date
from typing import Any

from conftest import company_facts, fact

from stock_metrics.sources.edgar import (
    AnnualFact,
    extract_annual_facts,
    fiscal_year_ends,
    fiscal_year_for,
    reporting_currency,
)


def by_concept(facts: list[AnnualFact], concept: str) -> dict[int, AnnualFact]:
    return {f.fiscal_year: f for f in facts if f.concept == concept}


def test_fiscal_year_label() -> None:
    assert fiscal_year_for(date(2023, 9, 30)) == 2023
    assert fiscal_year_for(date(2025, 1, 26)) == 2025  # NVIDIA-style late January
    assert fiscal_year_for(date(2022, 1, 1)) == 2021  # 52/53-week year spilling into Jan


def test_fiscal_year_ends(sample_facts: dict[str, Any]) -> None:
    assert fiscal_year_ends(sample_facts) == [date(2022, 9, 30), date(2023, 9, 30)]


def test_tag_switch_is_resolved_per_year(sample_facts: dict[str, Any]) -> None:
    revenue = by_concept(extract_annual_facts(sample_facts), "revenue")
    assert revenue[2022].value == 100.0
    assert revenue[2022].tag == "us-gaap:SalesRevenueNet"
    assert revenue[2023].value == 120.0  # quarterly 30.0 ignored


def test_latest_filing_wins(sample_facts: dict[str, Any]) -> None:
    ni = by_concept(extract_annual_facts(sample_facts), "net_income")
    assert ni[2022].value == 11.0
    assert ni[2022].filed == date(2023, 11, 1)


def test_instant_facts_only_at_fiscal_year_end(sample_facts: dict[str, Any]) -> None:
    equity = by_concept(extract_annual_facts(sample_facts), "equity")
    assert {fy: f.value for fy, f in equity.items()} == {2022: 50.0, 2023: 60.0}


def test_cover_page_shares_map_to_prior_year_end(sample_facts: dict[str, Any]) -> None:
    shares = by_concept(extract_annual_facts(sample_facts), "shares_outstanding_cover")
    assert shares[2022].period_end == date(2022, 9, 30)
    assert shares[2023].value == 10.0


def ifrs_facts() -> dict[str, Any]:
    """A 20-F filer reporting in MXN, plus a USD convenience translation of one year."""
    return company_facts(
        {},
        ifrs={
            "Revenue": {
                "MXN": [
                    fact(200.0, "2023-12-31", "2024-04-01", start="2023-01-01", form="20-F"),
                    fact(220.0, "2024-12-31", "2025-04-01", start="2024-01-01", form="20-F"),
                ],
                "USD": [fact(11.0, "2024-12-31", "2025-04-01", start="2024-01-01", form="20-F")],
            },
            "ProfitLossAttributableToOwnersOfParent": {
                "MXN": [fact(20.0, "2024-12-31", "2025-04-01", start="2024-01-01", form="20-F")]
            },
            "Equity": {"MXN": [fact(100.0, "2024-12-31", "2025-04-01", form="20-F")]},
            "DilutedEarningsLossPerShare": {
                "MXN/shares": [
                    fact(1.5, "2024-12-31", "2025-04-01", start="2024-01-01", form="20-F")
                ]
            },
        },
    )


def test_ifrs_filer_in_foreign_currency() -> None:
    facts = ifrs_facts()
    assert reporting_currency(facts) == "MXN"
    got = {(f.concept, f.fiscal_year): f for f in extract_annual_facts(facts)}
    assert got[("revenue", 2024)].value == 220.0  # MXN, not the USD translation
    assert got[("revenue", 2024)].tag == "ifrs-full:Revenue"
    assert got[("net_income", 2024)].value == 20.0
    assert got[("equity", 2024)].value == 100.0
    assert got[("eps_diluted", 2024)].value == 1.5
    assert got[("revenue", 2024)].form == "20-F"
