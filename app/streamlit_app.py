"""Stock Metrics dashboard. Run with:  streamlit run app/streamlit_app.py"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from stock_metrics.catalog import METRICS, METRICS_BY_KEY, Tab, metrics_for_tab
from stock_metrics.charts import (
    dual_axis_chart,
    format_pct,
    format_value,
    formatted_table,
    index_to_100,
    margin_overlay_chart,
    metric_chart,
    peer_chart,
    subtitle,
    window,
)
from stock_metrics.config import ConfigError, get_settings
from stock_metrics.export import metrics_workbook
from stock_metrics.metrics import yoy_growth
from stock_metrics.portfolio import PortfolioService, snapshot_row
from stock_metrics.service import (
    OVERRIDABLE_CONCEPTS,
    CompanyData,
    StockMetricsService,
    TickerNotFoundError,
)
from stock_metrics.sources.sharesight import SharesightAuthError

st.set_page_config(page_title="Stock Metrics", page_icon="📈", layout="wide")

TIMEFRAMES = {"3Y": 3, "5Y": 5, "10Y": 10, "Max": None}
PLOTLY_CONFIG = {"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}}
DISCLAIMER = (
    "Data: SEC EDGAR filings and Yahoo Finance prices. Figures are provided for research "
    "only and may contain errors — check against the filings before relying on them. "
    "Not financial advice."
)


@st.cache_resource
def get_service() -> StockMetricsService:
    return StockMetricsService(get_settings())


@st.cache_data(ttl=3600, show_spinner=False)
def load_tickers() -> pd.DataFrame:
    return get_service().ticker_list()


@st.cache_data(ttl=3600, show_spinner=False)
def load_company(ticker: str, refresh_token: int) -> CompanyData:
    # refresh_token changes when the user clicks "Refresh data", busting the cache.
    return get_service().company(ticker, force_refresh=refresh_token > 0)


def chart(fig: object, key: str) -> None:
    st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG, key=key)


def render_metric_grid(
    data: pd.DataFrame, keys: list[str], chart_type: str, show_trend: bool, prefix: str
) -> None:
    for i in range(0, len(keys), 2):
        cols = st.columns(2)
        for col, key in zip(cols, keys[i : i + 2], strict=False):
            metric = METRICS_BY_KEY[key]
            with col:
                st.markdown(f"**{metric.label}**", help=metric.definition)
                st.caption(subtitle(data[key], metric))
                chart(metric_chart(data, key, chart_type, show_trend), key=f"{prefix}-{key}")


def render_snapshot(company: CompanyData) -> None:
    m = company.metrics
    if m.empty:
        return
    latest = m.iloc[-1]
    fy = int(m.index[-1])
    tiles = [
        ("Revenue", "revenue", True),
        ("Net Margin", "net_margin", False),
        ("EPS (Diluted)", "eps_diluted", True),
        ("P/E", "pe", False),
        ("Dividend Yield", "dividend_yield", False),
        ("Debt / Equity", "debt_to_equity", False),
    ]
    fy_end = company.provenance["period_end"].dropna().max()
    st.caption(f"Snapshot · FY{fy} (fiscal year ended {fy_end})")
    # Two rows of three keeps values readable on laptop-width windows.
    cols = [c for _ in range(2) for c in st.columns(3)]
    for col, (label, key, show_growth) in zip(cols, tiles, strict=True):
        unit = METRICS_BY_KEY[key].unit
        delta = None
        if show_growth and len(m) > 1:
            g = yoy_growth(m[key]).iloc[-1]
            delta = f"{format_pct(g)} YoY" if pd.notna(g) else None
        col.metric(label, format_value(latest[key], unit), delta)


def render_sources(company: CompanyData) -> None:
    prov = company.provenance.copy()
    prov["metric"] = prov["concept"]

    def link(accn: object) -> str | None:
        if not isinstance(accn, str) or not accn:
            return None
        return f"https://www.sec.gov/Archives/edgar/data/{company.cik}/{accn.replace('-', '')}/"

    prov["filing"] = prov["accn"].map(link)
    st.dataframe(
        prov[
            ["concept", "fiscal_year", "value", "source", "tag", "filed", "filing", "override_note"]
        ],
        hide_index=True,
        use_container_width=True,
        column_config={
            "filing": st.column_config.LinkColumn("SEC filing", display_text="open"),
            "value": st.column_config.NumberColumn(format="%.4g"),
            "fiscal_year": st.column_config.NumberColumn("FY", format="%d"),
        },
    )


def page_dashboard(service: StockMetricsService) -> None:
    tickers = load_tickers()
    options = tickers["ticker"].tolist()
    names = dict(zip(tickers["ticker"], tickers["name"], strict=True))
    if "ticker" not in st.session_state:
        st.session_state.ticker = st.query_params.get("ticker", "AAPL").upper()
    if st.session_state.ticker not in names:
        st.session_state.ticker = "AAPL"

    with st.sidebar:
        st.selectbox(
            "Company",
            options,
            key="ticker",
            format_func=lambda t: f"{t} — {names.get(t, '')}",
            help="Type a ticker or company name to search.",
        )
        timeframe = st.segmented_control("Timeframe", list(TIMEFRAMES), default="10Y")
        chart_choice = st.segmented_control("Chart style", ["Auto", "Line", "Bar"], default="Auto")
        show_trend = st.toggle("CAGR trendlines & valuation bands", value=True)
        if st.button("Refresh data", help="Re-download from SEC and Yahoo Finance"):
            counts = st.session_state.setdefault("refresh", {})
            counts[st.session_state.ticker] = counts.get(st.session_state.ticker, 0) + 1
        st.divider()
        st.caption(DISCLAIMER)

    ticker = st.session_state.ticker
    st.query_params["ticker"] = ticker
    try:
        with st.spinner(f"Loading {ticker}…"):
            company = load_company(ticker, st.session_state.get("refresh", {}).get(ticker, 0))
    except TickerNotFoundError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # network/API failures shouldn't crash the page
        st.error(f"Couldn't load {ticker}: {exc}")
        return

    st.title(f"{company.name} ({company.ticker})")
    st.caption(f"Data cached {company.fetched_at:%d %b %Y %H:%M} UTC · SEC CIK {company.cik}")
    if company.metrics.empty:
        st.warning("No annual 10-K data found for this company.")
        return
    render_snapshot(company)

    data = window(company.metrics, TIMEFRAMES[timeframe or "10Y"])
    chart_type = (chart_choice or "Auto").lower()

    tab_labels = [t.value for t in Tab] + ["Compare", "Data & Sources"]
    tabs = st.tabs(tab_labels)
    for tab_enum, tab in zip(Tab, tabs, strict=False):
        with tab:
            if tab_enum is Tab.INCOME and st.toggle(
                "Overlay margins on revenue & profit", key="overlay"
            ):
                chart(margin_overlay_chart(data), key="overlay-chart")
            keys = [m.key for m in metrics_for_tab(tab_enum)]
            render_metric_grid(data, keys, chart_type, show_trend, prefix=tab_enum.name)

    with tabs[-2]:
        st.markdown("Plot any two metrics together on separate axes.")
        labels = {m.key: m.label for m in METRICS}
        c1, c2 = st.columns(2)
        left = c1.selectbox(
            "Left axis",
            list(labels),
            format_func=labels.get,
            index=list(labels).index("shares_outstanding"),
        )
        right = c2.selectbox(
            "Right axis",
            list(labels),
            format_func=labels.get,
            index=list(labels).index("eps_diluted"),
        )
        chart(dual_axis_chart(data, left, right), key="compare")

    with tabs[-1]:
        st.subheader("All metrics")
        table = formatted_table(data, [m.key for m in METRICS])
        st.dataframe(table, use_container_width=True)
        raw = data.copy()
        raw.index.name = "fiscal_year"
        c1, c2, _ = st.columns([1, 1, 3])
        c1.download_button(
            "Download metrics (CSV)",
            raw.to_csv().encode(),
            file_name=f"{ticker}_metrics.csv",
            mime="text/csv",
        )
        c2.download_button(
            "Download metrics (Excel)",
            metrics_workbook(ticker, company.name, data, company.provenance),
            file_name=f"{ticker}_metrics.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        st.subheader("Source figures")
        st.caption(
            "Every base figure with the SEC filing it came from. "
            "Manual overrides are marked as source 'manual'."
        )
        render_sources(company)


PEER_SNAPSHOT = ["revenue", "net_margin", "roic", "pe", "dividend_yield", "debt_to_equity"]


def page_peers(service: StockMetricsService) -> None:
    st.title("Peer comparison")
    tickers = load_tickers()
    names = dict(zip(tickers["ticker"], tickers["name"], strict=True))
    current = st.session_state.get("ticker", "AAPL")
    labels = {m.key: m.label for m in METRICS}

    chosen = st.multiselect(
        "Companies (up to 4)",
        tickers["ticker"].tolist(),
        default=[current],
        max_selections=4,
        format_func=lambda t: f"{t} — {names.get(t, '')}",
        key="peers",
    )
    c1, c2, c3, c4 = st.columns([2, 1.3, 1, 1.2])
    key = c1.selectbox(
        "Metric", list(labels), format_func=labels.get, index=list(labels).index("revenue")
    )
    timeframe = c2.segmented_control("Timeframe", list(TIMEFRAMES), default="10Y", key="pt")
    style = c3.segmented_control("Chart", ["Line", "Bar"], default="Line", key="ps")
    indexed = c4.toggle(
        "Index to 100",
        help="Rebase each company to 100 at the first year shown, to compare growth.",
    )
    if not chosen:
        st.info("Pick one or more companies to compare.")
        return

    companies: dict[str, CompanyData] = {}
    with st.spinner("Loading…"):
        for t in chosen:
            try:
                companies[t] = load_company(t, st.session_state.get("refresh", {}).get(t, 0))
            except TickerNotFoundError as exc:
                st.warning(str(exc))
            except Exception as exc:  # one bad ticker shouldn't hide the others
                st.warning(f"Couldn't load {t}: {exc}")
    companies = {t: c for t, c in companies.items() if not c.metrics.empty}
    if not companies:
        return

    last_year = max(int(c.metrics.index.max()) for c in companies.values())
    years = TIMEFRAMES[timeframe or "10Y"]
    first_year = last_year - years + 1 if years else None
    series = {}
    for t, c in companies.items():
        s = c.metrics[key]
        series[t] = s[s.index >= first_year] if first_year else s

    metric = METRICS_BY_KEY[key]
    st.markdown(f"**{metric.label}**", help=metric.definition)
    if indexed and any(index_to_100(s).isna().all() for s in series.values()):
        st.caption("Companies starting from zero or a negative value can't be indexed.")
    chart(
        peer_chart(series, key, indexed=indexed, chart_type=(style or "Line").lower()),
        key="peer-chart",
    )
    st.caption(
        "Years are fiscal years, which end in different months for different companies "
        "(e.g. Apple in September, Microsoft in June)."
    )

    all_years = sorted({int(y) for s in series.values() for y in s.index})
    table = pd.DataFrame(
        {
            t: [format_value(s.get(y), metric.unit) if y in s.index else "–" for y in all_years]
            for t, s in series.items()
        },
        index=[f"FY{y}" for y in all_years],
    ).T
    st.dataframe(table, use_container_width=True)

    st.subheader("Latest fiscal year snapshot")
    snapshot = pd.DataFrame(
        {
            t: {
                "Fiscal year": f"FY{int(c.metrics.index.max())}",
                **{
                    labels[k]: format_value(c.metrics[k].iloc[-1], METRICS_BY_KEY[k].unit)
                    for k in PEER_SNAPSHOT
                },
            }
            for t, c in companies.items()
        }
    )
    st.dataframe(snapshot, use_container_width=True)


PORTFOLIO_SETUP = """
**Connect Sharesight (read-only)**

1. In Sharesight, open **Account settings → Sharesight API** and create an API client
   (if you don't see that menu, email Sharesight support and ask for API access on your account).
2. Copy the **Client ID** and **Client Secret** into this project's `.env` file:

```
SHARESIGHT_CLIENT_ID=...
SHARESIGHT_CLIENT_SECRET=...
```

3. Restart the app, then come back to this page.
"""


def page_portfolio(service: StockMetricsService) -> None:
    st.title("Portfolio")
    portfolio = PortfolioService(service)
    if not portfolio.configured:
        st.info("Sharesight isn't connected yet.")
        st.markdown(PORTFOLIO_SETUP)
        return

    c1, c2 = st.columns([1, 4])
    try:
        if c1.button("Sync from Sharesight"):
            with st.spinner("Syncing holdings…"):
                n = portfolio.sync()
            st.success(f"Synced {n} holding(s).")
        else:
            portfolio.sync_if_stale()
    except SharesightAuthError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # network problems shouldn't crash the page
        st.error(f"Couldn't reach Sharesight: {exc}")
    synced = portfolio.synced_at()
    c2.caption(f"Last synced {synced:%d %b %Y %H:%M} UTC" if synced else "Not synced yet")

    holdings = portfolio.holdings()
    if holdings.empty:
        st.info("No holdings found.")
        return

    names = holdings[["portfolio_id", "portfolio"]].drop_duplicates()
    if len(names) > 1:
        chosen = st.selectbox("Portfolio", names["portfolio"].tolist())
        holdings = holdings[holdings["portfolio"] == chosen]
    currency = holdings["currency_code"].iloc[0]
    total = holdings["value"].sum()
    us_share = holdings.loc[holdings["linkable"], "value"].sum() / total if total else 0.0
    k1, k2, k3 = st.columns(3)
    k1.metric("Total value", f"{currency} {total:,.0f}")
    k2.metric("Holdings", len(holdings))
    k3.metric("US individual stocks", f"{us_share:.0%} of value")

    with_fundamentals = st.toggle(
        "Show fundamentals for US holdings",
        value=True,
        help="Loads each US company's SEC data (cached after the first load).",
    )
    rows = []
    linkable = holdings[holdings["linkable"]]
    progress = st.progress(0.0, "Loading company data…") if with_fundamentals else None
    for i, h in enumerate(holdings.itertuples()):
        row = {
            "Symbol": h.symbol,
            "Name": h.name,
            "Market": h.market,
            "Quantity": h.quantity,
            "Value": h.value,
            "Weight": h.weight,
            "Dashboard": f"dashboard?ticker={h.ticker}" if h.linkable else None,
        }
        if with_fundamentals and h.linkable:
            try:
                company = load_company(h.ticker, 0)
                snap = snapshot_row(company)
                row.update(
                    {
                        "FY": snap.get("fiscal_year"),
                        "P/E": snap.get("pe"),
                        "Div. yield": snap.get("dividend_yield"),
                        "Net margin": snap.get("net_margin"),
                        "ROIC": snap.get("roic"),
                        "Revenue CAGR 5Y": snap.get("revenue_cagr_5y"),
                    }
                )
            except Exception:  # one company failing shouldn't hide the table
                pass
        rows.append(row)
        if progress is not None and len(linkable):
            progress.progress(min(1.0, (i + 1) / len(holdings)), "Loading company data…")
    if progress is not None:
        progress.empty()

    table = pd.DataFrame(rows)
    pct = st.column_config.NumberColumn(format="percent")
    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Quantity": st.column_config.NumberColumn(format="%,.0f"),
            "Value": st.column_config.NumberColumn(f"Value ({currency})", format="%,.0f"),
            "Weight": pct,
            "Dashboard": st.column_config.LinkColumn(display_text="Open ↗"),
            "FY": st.column_config.NumberColumn(format="%d"),
            "P/E": st.column_config.NumberColumn(format="%.1fx"),
            "Div. yield": pct,
            "Net margin": pct,
            "ROIC": pct,
            "Revenue CAGR 5Y": pct,
        },
    )
    st.caption(
        "Fundamentals are for each company's latest fiscal year. Non-US holdings (e.g. ASX "
        "ETFs) are listed without fundamentals. 'Open ↗' opens the stock in a new tab."
    )

    if not linkable.empty:
        c1, c2 = st.columns([3, 1])
        pick = c1.selectbox(
            "Open a holding in the dashboard",
            linkable["ticker"].tolist(),
            format_func=lambda t: f"{t} — {linkable.set_index('ticker').loc[t, 'name']}",
        )
        c2.write("")
        if c2.button("Open"):
            st.session_state.ticker = pick
            st.switch_page(PAGES["dashboard"])


def page_overrides(service: StockMetricsService) -> None:
    st.title("Data corrections")
    st.markdown(
        "Upload a CSV to replace any base figure for a company and year. Corrections are "
        "kept when data is refreshed. Columns: `ticker, concept, fiscal_year, value, note` "
        "(`note` optional). Values are in USD (or USD per share / share count), split-adjusted."
    )
    with st.expander("Allowed concepts"):
        st.write(", ".join(f"`{c}`" for c in OVERRIDABLE_CONCEPTS))
    template = "ticker,concept,fiscal_year,value,note\nAAPL,revenue,2019,260174000000,example\n"
    st.download_button("Download template CSV", template, file_name="overrides_template.csv")

    upload = st.file_uploader("Upload corrections CSV", type="csv")
    if upload is not None and st.button("Import"):
        try:
            n = service.import_overrides_csv(upload.getvalue())
            st.success(f"Imported {n} correction(s).")
            load_company.clear()
        except ValueError as exc:
            st.error(str(exc))

    current = service.store.overrides()
    st.subheader("Current corrections")
    if current.empty:
        st.info("None yet.")
        return
    st.dataframe(current, hide_index=True, use_container_width=True)
    with st.form("delete"):
        labels = [f"{r.ticker} · {r.concept} · FY{r.fiscal_year}" for r in current.itertuples()]
        choice = st.selectbox(
            "Remove a correction", range(len(labels)), format_func=lambda i: labels[i]
        )
        if st.form_submit_button("Remove"):
            row = current.iloc[choice]
            service.store.delete_override(row["ticker"], row["concept"], int(row["fiscal_year"]))
            load_company.clear()
            st.rerun()


PAGES: dict[str, st.Page] = {}


def main() -> None:
    try:
        service = get_service()
    except ConfigError as exc:
        st.error(str(exc))
        st.stop()
    PAGES.update(
        dashboard=st.Page(
            lambda: page_dashboard(service),
            title="Dashboard",
            icon="📊",
            url_path="dashboard",
            default=True,
        ),
        peers=st.Page(lambda: page_peers(service), title="Peers", icon="⚖️", url_path="peers"),
        portfolio=st.Page(
            lambda: page_portfolio(service), title="Portfolio", icon="💼", url_path="portfolio"
        ),
        corrections=st.Page(
            lambda: page_overrides(service),
            title="Data corrections",
            icon="✏️",
            url_path="corrections",
        ),
    )
    st.navigation(list(PAGES.values())).run()


main()
