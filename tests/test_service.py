from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from stock_metrics.config import Settings
from stock_metrics.service import StockMetricsService, TickerNotFoundError, build_fact_rows
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


def test_company_without_10k_gives_friendly_error(
    tmp_path: Path, price_history: PriceHistory
) -> None:
    import requests

    class NotFoundEdgar(FakeEdgar):
        def company_facts(self, cik: int) -> dict[str, Any]:
            resp = requests.Response()
            resp.status_code = 404
            raise requests.HTTPError(response=resp)

    settings = Settings("t t@t.dev", tmp_path / "t.db", 7)
    svc = StockMetricsService(
        settings,
        edgar_client=NotFoundEdgar({}),  # type: ignore[arg-type]
        price_fetcher=lambda _t: price_history,
    )
    with pytest.raises(TickerNotFoundError, match="no annual"):
        svc.company("TEST")


def test_foreign_currency_and_adr_conversion() -> None:
    import pandas as pd

    from stock_metrics.sources.edgar import AnnualFact

    end, filed = date(2024, 12, 31), date(2025, 4, 1)

    def af(concept: str, value: float) -> AnnualFact:
        return AnnualFact(concept, 2024, end, value, "ifrs-full:X", "a", filed, "20-F")

    annual = [
        af("revenue", 1000.0),
        af("equity", 500.0),
        af("eps_diluted", 2.0),
        af("shares_outstanding", 800.0),
    ]
    days = pd.bdate_range("2024-01-01", "2024-12-31")
    # MXN worth 0.05 USD all year except 0.04 on the last day: flows use the
    # average (~0.05), balance-sheet items the year-end rate (0.04).
    fx = pd.Series(0.05, index=days)
    fx.iloc[-1] = 0.04
    history = PriceHistory(
        close=pd.Series(80.0, index=days),
        splits=pd.Series([2.0], index=pd.DatetimeIndex(["2025-06-01"])),
        dividends=pd.Series(dtype=float),
    )
    rows = {r.concept: r for r in build_fact_rows(annual, history, "MXN", fx, 10.0)}
    avg = fx[fx.index > "2024-01-01"].mean()  # fiscal year is (start, end]
    assert rows["revenue"].value == pytest.approx(1000 * avg)
    assert rows["equity"].value == pytest.approx(500 * 0.04)
    # Per ADR of 10 shares, converted at the average rate; ADRs skip split adjustment.
    assert rows["eps_diluted"].value == pytest.approx(2.0 * 10 * avg)
    assert rows["shares_outstanding"].value == pytest.approx(80.0)
    assert rows["price"].value == 80.0
    assert "MXN→USD" in (rows["revenue"].tag or "")


def test_missing_fx_rate_drops_money_figures() -> None:
    import pandas as pd

    from stock_metrics.sources.edgar import AnnualFact

    annual = [
        AnnualFact("revenue", 2024, date(2024, 12, 31), 1.0, "t", "a", date(2025, 4, 1), "20-F")
    ]
    empty = PriceHistory(pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float))
    assert build_fact_rows(annual, empty, "CAD", pd.Series(dtype=float)) == []


def test_store_migrates_old_companies_table(tmp_path: Path) -> None:
    import sqlite3

    from stock_metrics.store import Store

    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE companies (ticker TEXT PRIMARY KEY, cik INTEGER NOT NULL, "
        "name TEXT NOT NULL, fetched_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO companies VALUES ('OLD', 1, 'Old Co', '2026-01-01T00:00:00+00:00')")
    conn.commit()
    conn.close()
    info = Store(db).company("OLD")
    assert info is not None and info[3:] == ("USD", 1.0, "10-K")
