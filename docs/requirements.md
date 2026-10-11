# Stock Metrics: MVP Requirements and Decisions

This supersedes the original *Stock Metrics Tracking – Requirements Document* (.docx)
for the MVP. Guiding principles: **cheap, simple, quick**, and built to grow.

## Scope

| In the MVP | Later phases |
|---|---|
| US-listed companies that file 10-Ks with the SEC | Non-US companies |
| Annual data, 10+ years where filings allow | Quarterly data and TTM metrics |
| A single user running the app locally | Hosting, logins, multiple users |
| Five tabbed metric views, a compare view, data and sources | |
| Peer comparison (v1.1): up to 4 companies, raw or indexed | |
| CSV and Excel export, PNG chart download | |
| Manual corrections via CSV upload | Audit history of corrections |
| Sharesight portfolio sync (v1.2): read-only, Portfolio page | |
| | Moving averages, daily valuation bands |

## Decisions

| Topic | Decision |
|---|---|
| Financial data | SEC EDGAR XBRL company facts. Free, official, and traceable to filings. |
| Prices / splits / dividends | Yahoo Finance via yfinance. Free. |
| Paid data | None. FMP/Alpha Vantage only if a later phase needs them. |
| Storage | SQLite file in `data/`. |
| UI | Streamlit + Plotly. Core logic sits in `stock_metrics`, so an API or React front end can be added later without a rewrite. |
| Refresh | Fetched on first view, cached 7 days, plus a manual "Refresh data" button. |
| Devices | Desktop browsers. |
| Performance | Charts render in under 1.5s from cache. First fetch of a company takes a few seconds. |
| Secrets | SEC contact email and Sharesight Client ID/Secret live in a git-ignored `.env`. |
| CI | GitHub Actions: ruff (lint and format), mypy (types), pytest. |

## Metric definitions

| Metric | Definition |
|---|---|
| Fiscal year label | The calendar year the FY ends in. 52/53-week years ending 1–7 Jan count as the prior year. |
| Restatements | The latest filed value is used, and the filing is recorded. |
| Split adjustment | Per-share figures and share counts are adjusted for splits after the filing date. |
| Gross profit | As tagged. Otherwise revenue − cost of revenue. |
| EBITDA | Operating income + D&A (cash flow statement). |
| Free cash flow | Operating cash flow − capex. |
| Shares outstanding | Balance-sheet count at FY end, falling back to the 10-K cover page, then to weighted-average diluted shares (e.g. Meta, which only reports per-class counts). |
| Valuation price | Close on the last trading day of the FY. |
| P/E, P/S, P/B, P/FCF | Price / diluted EPS. Market cap / revenue, equity, FCF. N/M if the denominator is ≤ 0. |
| PEG | P/E / (3-year diluted EPS CAGR × 100). N/M if growth ≤ 0. |
| Dividend per share | SEC "declared" (or "cash paid") per share. Otherwise Yahoo dividends with ex-dates in the FY. |
| Dividend yield / payout | DPS / FY-end price. DPS / diluted EPS. |
| Total debt | LT debt incl. current portion + short-term borrowings (or commercial paper if no short-term borrowings are tagged, to avoid double counting). |
| D/E | Total debt / equity. N/M if equity ≤ 0. |
| Current / quick ratio | Current assets / current liabilities. (Cash + current marketable securities + receivables) / current liabilities. |
| ROE / ROA | Net income / year-end equity. Net income / year-end assets. |
| ROIC | EBIT × (1 − effective tax rate) / (total debt + equity − cash). The tax rate is clamped to 0–50%, defaulting to 21%. |

## Known limitations

- Banks and insurers don't report gross profit or current assets, so those metrics are blank.
- Berkshire Hathaway (and other companies with unusual share classes) report per-share figures that the tool doesn't map, so EPS and valuation ratios are blank.
- Figures are as filed. For example, Tesla's FY2025 share count (3.75B) reflects shares issued during 2025.
- SEC EPS is rounded to cents, so heavily split stocks show coarse early-year EPS.
- Quick ratio can be understated where a company stops tagging current marketable securities.
- Yahoo Finance is unofficial. If it breaks, prices and valuations go blank, but the SEC data still works.

## Acceptance checks (verified by hand against 10-Ks)

- Apple FY2025 revenue is $416.16B, diluted EPS $7.46, DPS $1.02.
- Coca-Cola FY2024 revenue is $47.06B, diluted EPS $2.46.
- NVIDIA FY2024 (ended Jan 2024) diluted EPS is $1.19 after the 2024 10-for-1 split.
- Microsoft FY2025 (ended Jun 2025) revenue is $281.72B.

## Roadmap

1. **MVP (this release):** data pipeline, five metric tabs, compare, sources, corrections, CI.
2. **v1.1 (done):** peer comparison (up to 4 tickers on one chart, raw or indexed to 100), Excel export, and a plain error for tickers with no 10-K data.
3. **v1.2 (done):** Sharesight read-only sync (v2 API, client credentials) and a Portfolio page with fundamentals and links into each US stock. The v3 API is still a closed beta, so v2 is used.
4. **Later:** quarterly and TTM data, daily valuation bands, hosting.
