"""Ties sources, cache and calculations together. The UI only talks to this module."""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from stock_metrics.config import Settings
from stock_metrics.metrics import compute_metrics
from stock_metrics.sources import edgar, prices
from stock_metrics.store import FactRow, Store

PER_SHARE_CONCEPTS = {"eps_basic", "eps_diluted", "dps"}
SHARE_COUNT_CONCEPTS = {"shares_outstanding", "shares_outstanding_cover"}
OVERRIDABLE_CONCEPTS = sorted({c.key for c in edgar.CONCEPTS} | {"price"})
TICKER_LIST_MAX_AGE = timedelta(days=30)


class TickerNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class CompanyData:
    ticker: str
    cik: int
    name: str
    fetched_at: datetime
    base: pd.DataFrame  # fiscal_year x base concept, overrides applied
    metrics: pd.DataFrame  # fiscal_year x metric key
    provenance: pd.DataFrame  # one row per base figure: source, tag, filing, override


def build_fact_rows(annual: list[edgar.AnnualFact], history: prices.PriceHistory) -> list[FactRow]:
    """Split-adjust SEC figures and add FY-end prices and dividend fallbacks."""
    rows: list[FactRow] = []
    period_ends: dict[int, date] = {}
    sec_dps_years: set[int] = set()

    for f in annual:
        value = f.value
        factor = prices.split_factor_after(history.splits, f.filed)
        if f.concept in PER_SHARE_CONCEPTS:
            value = value / factor
        elif f.concept in SHARE_COUNT_CONCEPTS:
            value = value * factor
        if f.concept == "dps":
            sec_dps_years.add(f.fiscal_year)
        period_ends[f.fiscal_year] = f.period_end
        rows.append(
            FactRow(
                concept=f.concept,
                fiscal_year=f.fiscal_year,
                period_end=f.period_end.isoformat(),
                value=value,
                source="sec",
                tag=f.tag + (f" (split-adjusted x{factor:g})" if factor != 1 else ""),
                accn=f.accn,
                filed=f.filed.isoformat(),
            )
        )

    years = sorted(period_ends)
    for i, fy in enumerate(years):
        end = period_ends[fy]
        px = prices.price_on_or_before(history.close, end)
        if px is not None:
            rows.append(
                FactRow(
                    "price",
                    fy,
                    end.isoformat(),
                    px,
                    "yahoo",
                    "Close on last trading day of FY (split-adjusted)",
                )
            )
        # Dividend fallback for years SEC data doesn't tag, only where we have
        # price history covering the whole year.
        start = period_ends[years[i - 1]] if i > 0 else end - timedelta(days=365)
        has_full_year = not history.close.empty and history.close.index[0] <= pd.Timestamp(start)
        if fy not in sec_dps_years and has_full_year:
            rows.append(
                FactRow(
                    "dps",
                    fy,
                    end.isoformat(),
                    prices.dividends_between(history.dividends, start, end),
                    "yahoo",
                    "Sum of dividends with ex-date in fiscal year (split-adjusted)",
                )
            )
    return rows


def _pivot(facts: pd.DataFrame) -> pd.DataFrame:
    if facts.empty:
        return pd.DataFrame()
    base = facts.pivot_table(index="fiscal_year", columns="concept", values="value", aggfunc="last")
    base.index = base.index.astype(int)
    return base.sort_index()


class StockMetricsService:
    def __init__(
        self,
        settings: Settings,
        edgar_client: edgar.EdgarClient | None = None,
        price_fetcher: Callable[[str], prices.PriceHistory] = prices.fetch_price_history,
    ) -> None:
        self.settings = settings
        self.store = Store(settings.db_path)
        self.edgar = edgar_client or edgar.EdgarClient(settings.sec_user_agent)
        self._fetch_prices = price_fetcher

    # --- ticker search ---
    def ticker_list(self) -> pd.DataFrame:
        refreshed = self.store.get_meta("tickers_refreshed_at")
        stale = refreshed is None or (
            datetime.now(UTC) - datetime.fromisoformat(refreshed) > TICKER_LIST_MAX_AGE
        )
        if stale:
            companies = self.edgar.ticker_list()
            self.store.replace_tickers((c.ticker, c.cik, c.name) for c in companies)
            self.store.set_meta("tickers_refreshed_at", datetime.now(UTC).isoformat())
        return self.store.tickers()

    # --- company data ---
    def refresh(self, ticker: str) -> None:
        ticker = ticker.upper()
        found = self.store.lookup_ticker(ticker)
        if found is None:
            self.ticker_list()
            found = self.store.lookup_ticker(ticker)
        if found is None:
            raise TickerNotFoundError(f"{ticker} is not in the SEC ticker list.")
        cik, name = found
        annual = edgar.extract_annual_facts(self.edgar.company_facts(cik))
        history = self._fetch_prices(ticker)
        self.store.save_company(ticker, cik, name, build_fact_rows(annual, history))

    def company(self, ticker: str, force_refresh: bool = False) -> CompanyData:
        ticker = ticker.upper()
        fetched_at = self.store.company_fetched_at(ticker)
        max_age = timedelta(days=self.settings.cache_days)
        if force_refresh or fetched_at is None or datetime.now(UTC) - fetched_at > max_age:
            self.refresh(ticker)

        info = self.store.company(ticker)
        assert info is not None
        cik, name, fetched_at = info
        facts = self.store.facts(ticker)
        overrides = self.store.overrides(ticker)

        provenance = facts.assign(overridden=False, override_note=None)
        if not overrides.empty:
            ov = overrides.assign(
                source="manual",
                tag="Manual override",
                accn=None,
                filed=None,
                period_end=None,
                overridden=True,
            ).rename(columns={"note": "override_note"})
            keys = ["concept", "fiscal_year"]
            provenance = provenance.merge(ov[keys], on=keys, how="left", indicator=True)
            provenance = provenance[provenance["_merge"] == "left_only"].drop(columns="_merge")
            provenance = pd.concat(
                [provenance, ov[provenance.columns.intersection(ov.columns)]],
                ignore_index=True,
            )

        base = _pivot(provenance)
        metrics = compute_metrics(base) if not base.empty else pd.DataFrame()
        return CompanyData(
            ticker,
            cik,
            name,
            fetched_at,
            base,
            metrics,
            provenance.sort_values(["concept", "fiscal_year"]),
        )

    # --- manual overrides ---
    def import_overrides_csv(self, data: bytes | str) -> int:
        """CSV columns: ticker, concept, fiscal_year, value, [note]."""
        text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
        df = pd.read_csv(io.StringIO(text))
        df.columns = [str(c).strip().lower() for c in df.columns]
        missing = {"ticker", "concept", "fiscal_year", "value"} - set(df.columns)
        if missing:
            raise ValueError(f"CSV is missing column(s): {', '.join(sorted(missing))}")
        unknown = set(df["concept"]) - set(OVERRIDABLE_CONCEPTS)
        if unknown:
            raise ValueError(
                f"Unknown concept(s): {', '.join(sorted(map(str, unknown)))}. "
                f"Allowed: {', '.join(OVERRIDABLE_CONCEPTS)}"
            )
        note_col: list[Any] = df["note"].tolist() if "note" in df.columns else [None] * len(df)
        rows = [
            (str(t), str(c), int(fy), float(v), None if pd.isna(n) else str(n))
            for t, c, fy, v, n in zip(
                df["ticker"],
                df["concept"],
                df["fiscal_year"],
                df["value"],
                note_col,
                strict=True,
            )
        ]
        return self.store.upsert_overrides(rows)
