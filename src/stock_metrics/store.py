"""Local SQLite cache for tickers, fetched figures and manual overrides."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickers (
    ticker TEXT PRIMARY KEY,
    cik INTEGER NOT NULL,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
    ticker TEXT PRIMARY KEY,
    cik INTEGER NOT NULL,
    name TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    ticker TEXT NOT NULL,
    concept TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    period_end TEXT NOT NULL,
    value REAL NOT NULL,
    source TEXT NOT NULL,       -- 'sec' or 'yahoo'
    tag TEXT,                   -- XBRL tag, or a description for Yahoo data
    accn TEXT,                  -- SEC accession number of the filing
    filed TEXT,                 -- date the filing was made
    PRIMARY KEY (ticker, concept, fiscal_year)
);
CREATE TABLE IF NOT EXISTS overrides (
    ticker TEXT NOT NULL,
    concept TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    value REAL NOT NULL,
    note TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (ticker, concept, fiscal_year)
);
CREATE TABLE IF NOT EXISTS sharesight_portfolios (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    currency_code TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sharesight_holdings (
    portfolio_id INTEGER NOT NULL,
    holding_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL,
    name TEXT NOT NULL,
    quantity REAL NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (portfolio_id, holding_id)
);
"""


@dataclass(frozen=True)
class FactRow:
    concept: str
    fiscal_year: int
    period_end: str
    value: float
    source: str
    tag: str | None = None
    accn: str | None = None
    filed: str | None = None


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- meta ---
    def get_meta(self, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # --- ticker list ---
    def replace_tickers(self, rows: Iterable[tuple[str, int, str]]) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM tickers")
            conn.executemany(
                "INSERT OR REPLACE INTO tickers (ticker, cik, name) VALUES (?, ?, ?)", rows
            )

    def tickers(self) -> pd.DataFrame:
        with self._conn() as conn:
            return pd.read_sql_query("SELECT ticker, cik, name FROM tickers ORDER BY ticker", conn)

    def lookup_ticker(self, ticker: str) -> tuple[int, str] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT cik, name FROM tickers WHERE ticker = ?", (ticker.upper(),)
            ).fetchone()
        return (int(row[0]), str(row[1])) if row else None

    # --- company facts ---
    def company_fetched_at(self, ticker: str) -> datetime | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT fetched_at FROM companies WHERE ticker = ?", (ticker,)
            ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def save_company(self, ticker: str, cik: int, name: str, facts: Iterable[FactRow]) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM facts WHERE ticker = ?", (ticker,))
            conn.executemany(
                "INSERT OR REPLACE INTO facts (ticker, concept, fiscal_year, period_end, value, "
                "source, tag, accn, filed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        ticker,
                        f.concept,
                        f.fiscal_year,
                        f.period_end,
                        f.value,
                        f.source,
                        f.tag,
                        f.accn,
                        f.filed,
                    )
                    for f in facts
                ],
            )
            conn.execute(
                "INSERT INTO companies (ticker, cik, name, fetched_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(ticker) DO UPDATE SET cik = excluded.cik, name = excluded.name, "
                "fetched_at = excluded.fetched_at",
                (ticker, cik, name, utcnow()),
            )

    def company(self, ticker: str) -> tuple[int, str, datetime] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT cik, name, fetched_at FROM companies WHERE ticker = ?", (ticker,)
            ).fetchone()
        return (int(row[0]), str(row[1]), datetime.fromisoformat(row[2])) if row else None

    def facts(self, ticker: str) -> pd.DataFrame:
        with self._conn() as conn:
            return pd.read_sql_query(
                "SELECT concept, fiscal_year, period_end, value, source, tag, accn, filed "
                "FROM facts WHERE ticker = ?",
                conn,
                params=(ticker,),
            )

    # --- overrides ---
    def upsert_overrides(self, rows: Iterable[tuple[str, str, int, float, str | None]]) -> int:
        now = utcnow()
        data = [(t.upper(), c, fy, v, note, now) for t, c, fy, v, note in rows]
        with self._conn() as conn:
            conn.executemany(
                "INSERT INTO overrides (ticker, concept, fiscal_year, value, note, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(ticker, concept, fiscal_year) DO UPDATE "
                "SET value = excluded.value, note = excluded.note, "
                "updated_at = excluded.updated_at",
                data,
            )
        return len(data)

    def overrides(self, ticker: str | None = None) -> pd.DataFrame:
        sql = "SELECT ticker, concept, fiscal_year, value, note, updated_at FROM overrides"
        params: tuple[str, ...] = ()
        if ticker:
            sql += " WHERE ticker = ?"
            params = (ticker.upper(),)
        with self._conn() as conn:
            return pd.read_sql_query(
                sql + " ORDER BY ticker, concept, fiscal_year", conn, params=params
            )

    def delete_override(self, ticker: str, concept: str, fiscal_year: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM overrides WHERE ticker = ? AND concept = ? AND fiscal_year = ?",
                (ticker.upper(), concept, fiscal_year),
            )

    # --- Sharesight portfolio snapshot ---
    def replace_portfolio_snapshot(
        self,
        portfolios: Iterable[tuple[int, str, str]],
        holdings: Iterable[tuple[int, int, str, str, str, float, float]],
    ) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sharesight_holdings")
            conn.execute("DELETE FROM sharesight_portfolios")
            conn.executemany(
                "INSERT INTO sharesight_portfolios (id, name, currency_code) VALUES (?, ?, ?)",
                portfolios,
            )
            conn.executemany(
                "INSERT INTO sharesight_holdings (portfolio_id, holding_id, symbol, market, "
                "name, quantity, value) VALUES (?, ?, ?, ?, ?, ?, ?)",
                holdings,
            )
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('sharesight_synced_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (utcnow(),),
            )

    def portfolio_snapshot(self) -> pd.DataFrame:
        with self._conn() as conn:
            return pd.read_sql_query(
                "SELECT p.id AS portfolio_id, p.name AS portfolio, p.currency_code, "
                "h.holding_id, h.symbol, h.market, h.name, h.quantity, h.value "
                "FROM sharesight_holdings h JOIN sharesight_portfolios p "
                "ON p.id = h.portfolio_id ORDER BY h.value DESC",
                conn,
            )
