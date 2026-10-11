from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from stock_metrics.config import Settings
from stock_metrics.service import StockMetricsService, build_fact_rows
from stock_metrics.sources.edgar import SecCompany, extract_annual_facts
from stock_metrics.sources.prices import PriceHistory


class FakeEdgar:
    def __init__(self, facts: dict[str, Any]) -> None:
        self.facts = facts

    def ticker_list(self) -> list[SecCompany]:
        return [SecCompany("TEST", 1, "Test Co")]

    def company_facts(self, cik: int) -> dict[str, Any]:
        return self.facts


@pytest.fixture
def service(
    tmp_path: Path, sample_facts: dict[str, Any], price_history: PriceHistory
) -> StockMetricsService:
    settings = Settings(
        sec_user_agent="test test@test.dev", db_path=tmp_path / "t.db", cache_days=7
    )
    return StockMetricsService(
        settings,
        edgar_client=FakeEdgar(sample_facts),  # type: ignore[arg-type]
        price_fetcher=lambda _t: price_history,
    )


def test_split_adjustment_uses_filing_date(
    sample_facts: dict[str, Any], price_history: PriceHistory
) -> None:
    rows = {
        (r.concept, r.fiscal_year): r
        for r in build_fact_rows(extract_annual_facts(sample_facts), price_history)
    }
    # FY2022 EPS filed before the 2-for-1 split -> halved; FY2023 filed after -> unchanged.
    assert rows[("eps_diluted", 2022)].value == 1.0
    assert rows[("eps_diluted", 2023)].value == 1.2
    assert rows[("shares_outstanding_cover", 2022)].value == 10.0
    assert rows[("shares_outstanding_cover", 2023)].value == 10.0


def test_prices_and_dividend_fallback(
    sample_facts: dict[str, Any], price_history: PriceHistory
) -> None:
    rows = {
        (r.concept, r.fiscal_year): r
        for r in build_fact_rows(extract_annual_facts(sample_facts), price_history)
    }
    assert rows[("price", 2023)].value == 10.0
    assert rows[("dps", 2022)].source == "yahoo"
    assert rows[("dps", 2022)].value == pytest.approx(0.2)  # Feb + Aug 2022
    assert rows[("dps", 2023)].value == pytest.approx(0.1)


def test_company_end_to_end(service: StockMetricsService) -> None:
    data = service.company("test")
    assert data.name == "Test Co"
    assert data.metrics.loc[2023, "net_margin"] == pytest.approx(0.1)
    assert data.metrics.loc[2023, "pe"] == pytest.approx(10.0 / 1.2)


def test_overrides_replace_values_and_survive_refresh(service: StockMetricsService) -> None:
    service.company("TEST")
    n = service.import_overrides_csv(
        "ticker,concept,fiscal_year,value,note\nTEST,revenue,2023,240,fixed typo\n"
    )
    assert n == 1
    data = service.company("TEST", force_refresh=True)
    assert data.base.loc[2023, "revenue"] == 240.0
    assert data.metrics.loc[2023, "net_margin"] == pytest.approx(0.05)
    row = data.provenance.query("concept == 'revenue' and fiscal_year == 2023").iloc[0]
    assert row["source"] == "manual"
    assert row["override_note"] == "fixed typo"


def test_override_rejects_unknown_concept(service: StockMetricsService) -> None:
    with pytest.raises(ValueError, match="Unknown concept"):
        service.import_overrides_csv("ticker,concept,fiscal_year,value\nTEST,pe,2023,10\n")
