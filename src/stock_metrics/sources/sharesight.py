"""Sharesight User API (v2), read-only: portfolios and current holdings.

Authentication uses the OAuth 2.0 client-credentials grant, which Sharesight
supports for reading your own account through your own API client. Access
tokens last 30 minutes and are refreshed automatically.

Docs: https://portfolio.sharesight.com/api/2/doc/index.html
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

TOKEN_URL = "https://api.sharesight.com/oauth2/token"
API_BASE = "https://api.sharesight.com/api/v2"

# Sharesight market codes for US exchanges. Holdings on these markets can be
# opened in the dashboard; everything else (ASX ETFs etc.) is listed only.
US_MARKETS = frozenset({"NASDAQ", "NYSE", "NYSE_ARCA", "NYSEAMERICAN", "AMEX", "BATS", "OTC"})


class SharesightAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class Portfolio:
    id: int
    name: str
    currency_code: str


@dataclass(frozen=True)
class Holding:
    portfolio_id: int
    holding_id: int
    symbol: str
    market: str
    name: str
    quantity: float
    value: float  # in the portfolio's currency

    @property
    def is_us(self) -> bool:
        return self.market.upper() in US_MARKETS

    @property
    def sec_ticker(self) -> str:
        """Ticker as SEC lists it (Sharesight writes share classes as BRK.B, SEC as BRK-B)."""
        return self.symbol.upper().replace(".", "-")


class SharesightClient:
    def __init__(self, client_id: str, client_secret: str, timeout: float = 30.0) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout
        self._session = requests.Session()
        self._token: str | None = None
        self._token_expires = 0.0

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires - 60:
            return self._token
        resp = self._session.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=self._timeout,
        )
        if resp.status_code in (400, 401, 403):
            raise SharesightAuthError(
                "Sharesight rejected the Client ID/Secret. Check SHARESIGHT_CLIENT_ID and "
                "SHARESIGHT_CLIENT_SECRET in .env, and that API access is enabled on your account."
            )
        resp.raise_for_status()
        body = resp.json()
        self._token = str(body["access_token"])
        self._token_expires = time.monotonic() + float(body.get("expires_in", 1800))
        return self._token

    def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        resp = self._session.get(
            f"{API_BASE}/{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._access_token()}"},
            timeout=self._timeout,
        )
        if resp.status_code in (401, 403, 412):
            raise SharesightAuthError(
                f"Sharesight refused access ({resp.status_code}). The API client may not be "
                "linked to your account, or access was revoked."
            )
        resp.raise_for_status()
        return resp.json()

    def portfolios(self) -> list[Portfolio]:
        data = self._get("portfolios.json")
        return parse_portfolios(data)

    def holdings(self, portfolio_id: int) -> list[Holding]:
        data = self._get(
            f"portfolios/{portfolio_id}/valuation.json", params={"grouping": "ungrouped"}
        )
        return parse_valuation(portfolio_id, data)


def parse_portfolios(data: dict[str, Any]) -> list[Portfolio]:
    return [
        Portfolio(
            id=int(p["id"]), name=str(p["name"]), currency_code=str(p.get("currency_code", ""))
        )
        for p in data.get("portfolios", [])
    ]


def parse_valuation(portfolio_id: int, data: dict[str, Any]) -> list[Holding]:
    out = []
    for h in data.get("holdings", []):
        quantity = float(h.get("quantity") or 0)
        if quantity == 0:
            continue  # sold-out positions
        out.append(
            Holding(
                portfolio_id=portfolio_id,
                holding_id=int(h["id"]),
                symbol=str(h.get("symbol", "")),
                market=str(h.get("market") or h.get("market_code") or ""),
                name=str(h.get("name", "")),
                quantity=quantity,
                value=float(h.get("value") or 0),
            )
        )
    return out
