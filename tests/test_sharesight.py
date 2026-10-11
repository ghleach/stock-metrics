from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from stock_metrics.config import Settings
from stock_metrics.portfolio import PortfolioService, SharesightNotConfiguredError, snapshot_row
from stock_metrics.service import CompanyData, StockMetricsService
from stock_metrics.sources.edgar import SecCompany
from stock_metrics.sources.sharesight import (
    Portfolio,
    SharesightAuthError,
    SharesightClient,
    parse_portfolios,
    parse_valuation,
)

PORTFOLIOS = {"portfolios": [{"id": 7, "name": "Main", "currency_code": "AUD"}]}
VALUATION = {
    "holdings": [
        {
            "id": 1,
            "symbol": "AAPL",
            "market": "NASDAQ",
            "name": "Apple",
            "quantity": 10,
            "value": 5000.0,
        },
        {
            "id": 2,
            "symbol": "BRK.B",
            "market": "NYSE",
            "name": "Berkshire B",
            "quantity": 2,
            "value": 1500.0,
        },
        {
            "id": 3,
            "symbol": "IVV",
            "market": "ASX",
            "name": "iShares S&P 500",
            "quantity": 50,
            "value": 3500.0,
        },
        {
            "id": 4,
            "symbol": "OLD",
            "market": "NYSE",
            "name": "Sold out",
            "quantity": 0,
            "value": 0.0,
        },
    ]
}


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, token_status: int = 200) -> None:
        self.token_status = token_status
        self.token_calls = 0
        self.gets: list[tuple[str, dict[str, str] | None, str]] = []

    def post(self, url: str, data: dict[str, str], timeout: float) -> FakeResponse:
        self.token_calls += 1
        assert data["grant_type"] == "client_credentials"
        return FakeResponse(self.token_status, {"access_token": "tok", "expires_in": 1800})

    def get(
        self, url: str, params: dict[str, str] | None, headers: dict[str, str], timeout: float
    ) -> FakeResponse:
        self.gets.append((url, params, headers["Authorization"]))
        body = PORTFOLIOS if url.endswith("portfolios.json") else VALUATION
        return FakeResponse(200, body)


def make_client(session: FakeSession) -> SharesightClient:
    client = SharesightClient("id", "secret")
    client._session = session  # type: ignore[assignment]
    return client


def test_parse_valuation_skips_sold_positions() -> None:
    holdings = parse_valuation(7, VALUATION)
    assert [h.symbol for h in holdings] == ["AAPL", "BRK.B", "IVV"]
    brk = holdings[1]
    assert brk.is_us and brk.sec_ticker == "BRK-B"
    assert not holdings[2].is_us


def test_parse_portfolios() -> None:
    assert parse_portfolios(PORTFOLIOS) == [Portfolio(7, "Main", "AUD")]


def test_client_reuses_token_and_requests_ungrouped_valuation() -> None:
    session = FakeSession()
    client = make_client(session)
    assert client.portfolios()[0].id == 7
    assert len(client.holdings(7)) == 3
    assert session.token_calls == 1
    url, params, auth = session.gets[1]
    assert url.endswith("/api/v2/portfolios/7/valuation.json")
    assert params == {"grouping": "ungrouped"}
    assert auth == "Bearer tok"


def test_client_reports_bad_credentials() -> None:
    client = make_client(FakeSession(token_status=401))
    with pytest.raises(SharesightAuthError):
        client.portfolios()


class FakeEdgar:
    def ticker_list(self) -> list[SecCompany]:
        return [SecCompany("AAPL", 320193, "Apple Inc."), SecCompany("BRK-B", 1067983, "BRK")]


@pytest.fixture
def metrics_service(tmp_path: Path) -> StockMetricsService:
    settings = Settings("t t@t.dev", tmp_path / "t.db", 7)
    return StockMetricsService(settings, edgar_client=FakeEdgar())  # type: ignore[arg-type]


def test_not_configured(metrics_service: StockMetricsService) -> None:
    svc = PortfolioService(metrics_service)
    assert not svc.configured
    with pytest.raises(SharesightNotConfiguredError):
        svc.sync()


def test_sync_and_holdings_table(metrics_service: StockMetricsService) -> None:
    session = FakeSession()
    svc = PortfolioService(metrics_service, client_factory=lambda: make_client(session))
    assert svc.sync() == 3
    assert svc.synced_at() is not None

    df = svc.holdings().set_index("symbol")
    assert df.loc["AAPL", "weight"] == pytest.approx(0.5)
    assert bool(df.loc["AAPL", "linkable"])
    assert df.loc["BRK.B", "ticker"] == "BRK-B" and bool(df.loc["BRK.B", "linkable"])
    assert not bool(df.loc["IVV", "linkable"])
    assert (df["currency_code"] == "AUD").all()

    # A second sync replaces rather than duplicates.
    svc.sync()
    assert len(svc.holdings()) == 3
    # Fresh snapshot: no re-sync needed.
    svc.sync_if_stale()
    assert session.token_calls == 2


def test_snapshot_row() -> None:
    metrics = pd.DataFrame(
        {
            "revenue": [100.0, 0, 0, 0, 0, 161.051],
            "pe": [0, 0, 0, 0, 0, 20.0],
            "dividend_yield": [0, 0, 0, 0, 0, 0.02],
            "net_margin": [0, 0, 0, 0, 0, 0.1],
            "roic": [0, 0, 0, 0, 0, 0.15],
        },
        index=range(2020, 2026),
    )
    company = CompanyData("X", 1, "X", None, pd.DataFrame(), metrics, pd.DataFrame())  # type: ignore[arg-type]
    row = snapshot_row(company)
    assert row["fiscal_year"] == 2025
    assert row["pe"] == 20.0
    assert row["revenue_cagr_5y"] == pytest.approx(0.10)
