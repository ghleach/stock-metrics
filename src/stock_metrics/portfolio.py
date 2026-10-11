"""Sharesight portfolio sync and the holdings table shown on the Portfolio page."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pandas as pd

from stock_metrics.service import CompanyData, StockMetricsService
from stock_metrics.sources.sharesight import US_MARKETS, Holding, SharesightClient

SNAPSHOT_METRICS = ("pe", "dividend_yield", "net_margin", "roic", "revenue_cagr_5y")


class SharesightNotConfiguredError(RuntimeError):
    pass


class PortfolioService:
    def __init__(
        self,
        metrics_service: StockMetricsService,
        client_factory: Callable[[], SharesightClient] | None = None,
    ) -> None:
        self.metrics = metrics_service
        self.store = metrics_service.store
        settings = metrics_service.settings
        if client_factory is None and settings.sharesight_configured:
            assert settings.sharesight_client_id and settings.sharesight_client_secret
            cid, secret = settings.sharesight_client_id, settings.sharesight_client_secret

            def client_factory() -> SharesightClient:
                return SharesightClient(cid, secret)

        self._client_factory = client_factory

    @property
    def configured(self) -> bool:
        return self._client_factory is not None

    def synced_at(self) -> datetime | None:
        value = self.store.get_meta("sharesight_synced_at")
        return datetime.fromisoformat(value) if value else None

    def sync(self) -> int:
        """Replace the local snapshot with current Sharesight holdings. Returns holding count."""
        if self._client_factory is None:
            raise SharesightNotConfiguredError(
                "Add SHARESIGHT_CLIENT_ID and SHARESIGHT_CLIENT_SECRET to .env to enable sync."
            )
        client = self._client_factory()
        portfolios = client.portfolios()
        holdings: list[Holding] = []
        for p in portfolios:
            holdings.extend(client.holdings(p.id))
        self.store.replace_portfolio_snapshot(
            [(p.id, p.name, p.currency_code) for p in portfolios],
            [
                (h.portfolio_id, h.holding_id, h.symbol, h.market, h.name, h.quantity, h.value)
                for h in holdings
            ],
        )
        return len(holdings)

    def sync_if_stale(self) -> None:
        last = self.synced_at()
        max_age = timedelta(days=self.metrics.settings.cache_days)
        if self.configured and (last is None or datetime.now(UTC) - last > max_age):
            self.sync()

    def holdings(self) -> pd.DataFrame:
        """Snapshot holdings with weight, US flag and the SEC ticker to link to."""
        df = self.store.portfolio_snapshot()
        if df.empty:
            return df
        totals = df.groupby("portfolio_id")["value"].transform("sum")
        df["weight"] = (df["value"] / totals.where(totals != 0)).astype(float)
        df["is_us"] = df["market"].str.upper().isin(US_MARKETS)
        df["ticker"] = df["symbol"].str.upper().str.replace(".", "-", regex=False)
        known = set(self.metrics.ticker_list()["ticker"])
        df["linkable"] = df["is_us"] & df["ticker"].isin(known)
        return df


def snapshot_row(company: CompanyData) -> dict[str, float]:
    """Latest-FY fundamentals for one company, for the holdings table."""
    m = company.metrics
    if m.empty:
        return {}
    latest = m.iloc[-1]
    row = {k: float(latest[k]) for k in ("pe", "dividend_yield", "net_margin", "roic")}
    revenue = m["revenue"].dropna()
    fy = int(m.index[-1])
    if fy in revenue.index and (fy - 5) in revenue.index and revenue[fy - 5] > 0:
        row["revenue_cagr_5y"] = float((revenue[fy] / revenue[fy - 5]) ** 0.2 - 1)
    else:
        row["revenue_cagr_5y"] = float("nan")
    row["fiscal_year"] = fy
    return row
