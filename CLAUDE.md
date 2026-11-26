# Notes for Claude

Stock Metrics is a local Streamlit dashboard of long-term fundamentals for US-listed
companies. Financial figures come from SEC EDGAR XBRL. Prices, splits and dividends
come from Yahoo Finance. Holdings come from Sharesight (optional). Everything is
cached in SQLite. The README covers features and setup; this file covers the rules.

## Commands
- Run: `.venv/bin/streamlit run app/streamlit_app.py` -> http://localhost:8501
  (`.claude/launch.json` holds the same launch config)
- Lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- Types: `.venv/bin/mypy` (strict)
- Tests: `.venv/bin/pytest -q -m "not network"`. CI runs exactly this; tests marked
  `network` call live APIs and are opt-in.
- CI (`.github/workflows/ci.yml`) runs lint, mypy and tests on every push and PR.
  Keep all three green.

## Layering (keep it)
`sources/` fetch raw data -> `service.py` orchestrates (FX, splits, cache) ->
`store.py` SQLite -> `metrics.py` pure formulas -> `charts.py` / `export.py` ->
`app/streamlit_app.py`. The UI talks only to `service.py`. `metrics.py` stays
side-effect free. Metric definitions belong in `catalog.py`.

## Data rules learned the hard way
- **XBRL tags:** each figure has a priority list of US-GAAP (or IFRS) tags, resolved
  per year, because companies change tags. When a figure is restated, take the
  most recently *filed* value. Add new tags to the priority lists; don't hard-code
  per-company fixes.
- **Foreign filers** (20-F/40-F, e.g. KOF, GFL, NU, DLO): read IFRS tags, convert
  to USD and show per ADR using the ratio table in `sources/prices.py`.
- **TTM:** trailing-twelve-months rows use the sentinel `TTM_FISCAL_YEAR = 9999`
  (edgar.py, mirrored in metrics.py). Flow items sum the last four 10-Q quarters
  (periods of 70-100 days); balance-sheet items use the latest quarter.
  `series_cagr()` and `window()` exclude or anchor on it. Labels show "TTM" via
  `_fy_label()`, never "FY9999". Any new metric, chart or export must handle 9999.
- **No NaN in SQLite:** sparse SEC quarterly data produces NaN. The `facts` table is
  NOT NULL, and a NaN crashed KLAC. Guards exist in edgar.py, service.py and
  store.py. Keep all three, and never insert a non-finite value.
- **SEC fair access:** keep the 0.11 s sleep before every EDGAR request (≤10/s), and
  always send `SEC_USER_AGENT` (from `.env`).
- **yfinance:** always pass `timeout=30`.
- **Capex:** take `abs()` before subtracting from operating cash flow (companies tag
  the sign differently).
- **ROIC:** invested capital ≤ 0 is masked, so the result shows N/M rather than a
  misleading ratio. Ratios that are meaningless (e.g. P/E with negative EPS) also show N/M.
- **Ticker search:** a custom `text_input` with a ranked filter (exact ticker, then
  ticker prefix, then name contains). Don't go back to Streamlit's fuzzy selectbox
  search: "CRM" matched "Critical Metals" before Salesforce.
- Streamlit: use `width="stretch"`, not the deprecated `use_container_width`.

## Secrets and data
- `.env` (git-ignored) holds `SEC_USER_AGENT`, plus `SHARESIGHT_CLIENT_ID` /
  `SHARESIGHT_CLIENT_SECRET` for the optional Portfolio page. Never print, log or
  commit them.
- The Sharesight client is read-only (GET only). Keep it that way.
- `data/stock_metrics.db` is a local cache. Don't commit it.
- Manual overrides (Data corrections page) must survive refreshes.

## Working in Claude's cloud workspace
The cloud workspace can't pip-install or reach SEC/Yahoo, so the app and tests
usually can't run there. Check changes by reading the code and running whatever
does work locally, then say plainly what wasn't run. The repo is public: no
secrets, account numbers or personal holdings in commits.
