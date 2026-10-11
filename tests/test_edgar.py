from __future__ import annotations

from datetime import date
from typing import Any

from stock_metrics.sources.edgar import (
    AnnualFact,
    extract_annual_facts,
    fiscal_year_ends,
    fiscal_year_for,
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
