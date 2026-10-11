# Stock Metrics

A local dashboard for long-term fundamental trends in US-listed companies:
revenue, margins, EPS, valuation multiples, dividends, balance-sheet health and
returns on capital. It covers 10+ years of annual data, drawn from SEC filings and Yahoo
Finance prices.

Not financial advice. Figures are for research and may contain errors.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env        # then edit SEC_USER_AGENT (see below)
.venv/bin/streamlit run app/streamlit_app.py
```

Open http://localhost:8501.

### SEC contact email

The SEC asks every automated client to identify itself with a name and contact
email ([SEC fair-access policy](https://www.sec.gov/os/accessing-edgar-data)).
Put yours in `.env`, which is git-ignored:

```
SEC_USER_AGENT="stock-metrics your.name@example.com"
```

## What's in the app

| Tab | Metrics |
|---|---|
| Financial Performance | Revenue, gross profit, operating income, EBITDA, net income, free cash flow, EPS (diluted and basic), plus an optional margin overlay |
| Profitability & Margins | Gross/operating/net margin, ROE, ROA, ROIC |
| Valuation & Price Multiples | FY-end price, market cap, P/E, P/S, P/B, P/FCF, PEG, each with a historical average and ±1 std-dev band |
| Dividends & Shareholder Returns | Dividend per share, yield, payout ratio, shares outstanding |
| Balance Sheet & Financial Health | Current ratio, quick ratio, debt-to-equity, total debt, cash, equity |
| Compare | Any two metrics on a dual-axis chart |
| Data & Sources | Full table, CSV and Excel download, and every base figure linked to its SEC filing |

Controls: ticker search (type a ticker or company name), timeframe (3Y / 5Y / 10Y / Max),
line or bar charts, and CAGR trendlines. Hover over any point to see the value and its YoY change. Use the
camera icon on each chart to download a PNG.

**Peers** (sidebar page): overlay one metric for up to 4 companies, as raw values or indexed
to 100 at the first year shown, plus a latest-year snapshot table.

**Data corrections** (sidebar page): upload a CSV to override any base figure.
Overrides survive refreshes and show as `manual` in Data & Sources.

## How the data works

- **Financials** come from SEC EDGAR [company facts](https://www.sec.gov/edgar/sec-api-documentation)
  (XBRL in 10-K filings). Each figure has a priority list of US-GAAP tags, resolved per year,
  because companies change tags over time. When a figure is restated, the most recent filing's
  value is used. See `src/stock_metrics/sources/edgar.py`.
- **Prices, splits and dividends** come from Yahoo Finance via `yfinance`.
- **Split adjustment**: per-share figures and share counts are adjusted for any split
  that happened after the filing they came from.
- **Caching**: everything is cached in `data/stock_metrics.db` (SQLite) and refreshed after 7 days,
  or on demand with "Refresh data".
- **Metric definitions** live in `src/stock_metrics/catalog.py`, and the formulas in
  `src/stock_metrics/metrics.py`. Meaningless ratios (for example P/E with negative EPS) show as N/M.

## Project layout

```
app/streamlit_app.py          UI (Streamlit)
src/stock_metrics/
  catalog.py                  metric definitions, units, tabs
  metrics.py                  derived-metric formulas (pure functions)
  charts.py                   Plotly figures and number formatting
  export.py                   Excel workbook export
  service.py                  orchestration: fetch → adjust → cache → compute
  store.py                    SQLite cache and manual overrides
  sources/edgar.py            SEC EDGAR client and XBRL tag mapping
  sources/prices.py           Yahoo Finance prices, splits, dividends
tests/                        pytest suite (no network)
docs/requirements.md          MVP requirements and decisions
```

## Development

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pytest -q
```

GitHub Actions runs the same checks on every push and pull request.
