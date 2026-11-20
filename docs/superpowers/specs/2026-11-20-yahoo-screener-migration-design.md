# Yahoo Screener Migration — Design

## Intent

Replace Finnhub as Stonks' market-data source with the free Yahoo Finance screener exposed through `yfinance`, while keeping the existing local preset/filter/SQLite/Streamlit layer and guaranteeing that every filter used by `POPULAR_SCREENS` still produces correct results.

## Why

Finnhub has no server-side screener. The worker currently downloads metrics symbol-by-symbol for the whole market, then filters locally; that is slow and expensive (the user's exact complaint: *"FinHub doesn't provide filters so i have to ingest the entire fucking market for my filters to work ..."*). stockanalysis.com has the desired screener UX but explicitly forbids programmatic access and bulk collection, so it cannot be the data source. Yahoo's screener is free, needs no API key, supports server-side filters, and exposes the fields Stonks needs.

## Goals

- No Finnhub dependency, no `FINNHUB_API_KEY`, no per-symbol calls for the entire market.
- Use Yahoo's server-side screener to narrow the candidate universe before any per-symbol work.
- Every filter in every entry of `POPULAR_SCREENS` must be enforced on the final rows, including 5Y/10Y/15Y metrics Yahoo cannot filter directly.
- Keep the existing Streamlit UI, saved screens, watchlist, view presets, sorting and pagination behaviour unchanged.
- Cache enrichment in the existing SQLite `stocks` table so repeat runs are cheap.
- Work on the free tier with no API key.

## Non-goals / Anti-goals

- No scraping of stockanalysis.com (ToS forbids it; API access does not exist).
- No paid FMP plan.
- No intraday/tick data; this is daily/TTM stock screening and technical analysis.
- No DCF / Peter Lynch fair-value features and no HedgeFollow data in this change.
- No rewrite of the UI or the filter model.

## Constraints & Decisions

- **Data source decision (confirmed by user: "yeap go"):** free Yahoo Finance via `yfinance`, not paid FMP and not stockanalysis.com.
- **Provider shape:** a new `YahooProvider` in `src/stonks/yahoo.py` owns all Yahoo access. No other module imports `yfinance`.
- **Two-stage fetch:**
  1. `screen()` pages the Yahoo screener (max 250 rows/request) and returns quote-level fields plus candidate symbols.
  2. `enrich()` fetches per-symbol fundamentals only for candidate symbols, then computes the derived columns locally.
- **Deep-field reality:** Yahoo accepts screener predicates on fields such as `returnontotalcapital.lasttwelvemonths`, `grossprofitmargin.lasttwelvemonths` and `pctheldinsider`, but does **not** return those values in the quote payload. Never read a value from the screener response just because it was used as a filter.
- **Preset candidate union:** the worker derives server-side queries from `POPULAR_SCREENS`, collects the union of candidate symbols, and enriches that union. Presets therefore work without a full-market per-symbol crawl.
- **Final filtering remains local:** `SQLiteStore.get_stocks` stays the authority for exact min/max/enum filtering and sorting. Yahoo filters are a performance prefilter; local derivation guarantees exactness.
- **Units (must be exact):**
  - Stonks `market_cap` is in **millions** (presets use `1000` = $1B); Yahoo `intradaymarketcap` is raw dollars → multiply by 1e6.
  - `free_cash_flow` and `net_income` are stored in **millions**; Yahoo `leveredfreecashflow.lasttwelvemonths` / `netincomeis.lasttwelvemonths` are raw dollars → divide by 1e6 on ingest.
  - `dividend_yield_pct` is percent (2.62), Yahoo screener `dividendyield` is also percent (2.62) — no conversion.
  - `shares_insiders_pct` is a fraction (0.01 = 1%), Yahoo `pctheldinsider` is a fraction — no conversion.
  - `Ticker.info` margins/ROE/ROA are decimals → multiply by 100 for Stonks percent columns; `info['debtToEquity']` is percent (280.26 = 2.8026) → divide by 100.
- **Missing data:** derived columns that cannot be computed are stored as `NULL`. `SQLiteStore` already sorts `NULLS LAST` and excludes NULLs from min/max matches; never invent placeholder values (in particular remove the old `shares_insiders_pct = 1.0` hack).
- **Resilience:** Yahoo requests can fail or throttle. Retry with bounded backoff, skip the symbol on persistent failure, keep existing cached values, and record status in `sync_status`. A failed refresh must never delete previously stored rows.
- **Caching:** enrich only symbols whose derived data is missing or older than a configurable TTL (default 7 days). Quote fields refresh on every worker run via the cheap screener.
- **Dependency:** add `yfinance>=1.8.0`; remove `finnhub-python`, `FINNHUB_API_KEY`, and the Finnhub rate limiter.
- **Python:** 3.12 (project `.python-version`), Streamlit app, `uv` for dependency management, `pytest` for tests.

## Field Mapping (our column → Yahoo)

### Screener fields (used as server-side prefilter where available)

| Stonks column | Yahoo screener field | Conversion |
|---|---|---|
| market_cap | intradaymarketcap | × 1e6 |
| pe_ratio | peratio.lasttwelvemonths | identity |
| pb_ratio | pricebookratio.quarterly | identity |
| dividend_yield_pct | dividendyield | identity |
| roe_pct | returnonequity.lasttwelvemonths | identity |
| gross_margin_pct | grossprofitmargin.lasttwelvemonths | identity |
| debt_to_equity | totaldebtequity.lasttwelvemonths | identity |
| current_ratio | currentratio.lasttwelvemonths | identity |
| roic_pct | returnontotalcapital.lasttwelvemonths | identity |
| shares_insiders_pct | pctheldinsider | identity |
| free_cash_flow | leveredfreecashflow.lasttwelvemonths | × 1e6 |
| net_income | netincomeis.lasttwelvemonths | × 1e6 |

Not server-filterable (derive locally): `roic_5y_avg_pct`, `roa_5y_avg_pct`, `roe_5y_avg_pct`, `return_cagr_{5,10,15}y_pct`, `revenue_growth_{3,5}y_pct`, `eps_growth_5y_pct`, `fcf_growth_5y_pct`, `net_income_growth_5y_pct`, `operating_margin_pct`.

### Quote payload (returned, no extra request)

`symbol`, `shortName`/`longName`, `exchange`, `fullExchangeName`, `currency`, `marketCap`, `regularMarketPrice`, `trailingPE`, `forwardPE`, `priceToBook`, `bookValue`, `dividendYield`, `epsTrailingTwelveMonths`, `fiftyTwoWeekHigh`, `fiftyTwoWeekLow`, `averageDailyVolume3Month`, `averageAnalystRating`, `beta`, `shortPercentageOfFloat`.

### Fundamentals (per-symbol, cached)

- `Ticker.info`: `grossMargins`, `operatingMargins`, `profitMargins`, `returnOnAssets`, `returnOnEquity`, `debtToEquity`, `currentRatio`, `freeCashflow`, `heldPercentInsiders`, `totalDebt`, `totalCash`, `revenueGrowth`, `earningsGrowth`, `ebitdaMargins`, `netIncomeToCommon`.
- `Ticker.history(period="15y", interval="1mo", auto_adjust=True)`: price CAGRs for 5/10/15 years using month-end closes.
- `Ticker.financials` / `balance_sheet` / `cashflow` (annual): 5Y averages and growth rates. Use up to 5 available annual periods; if fewer exist, compute over what is available and store `NULL` when fewer than 2 points exist.

## Derived metric definitions

- `return_cagr_ny_pct = ((P_end / P_start) ** (1/n) - 1) * 100`, using month-end adjusted closes `n` years apart.
- `roa_5y_avg_pct`, `roe_5y_avg_pct`, `roic_5y_avg_pct`: arithmetic mean of available annual values (`Net Income / Total Assets`, `Net Income / Total Equity`, `EBIT / (Total Debt + Total Equity)`), ×100.
- `revenue_growth_5y_pct`, `eps_growth_5y_pct`, `fcf_growth_5y_pct`, `net_income_growth_5y_pct`: CAGR of the corresponding annual series over the available span (5Y when 6 points exist).
- `operating_margin_pct`: `Operating Income / Total Revenue × 100` from annual financials (not EBITDA margin).
- `fcf_growth_5y_pct` uses `Free Cash Flow` from the cashflow statement.

## Files

- Create `src/stonks/yahoo.py` — provider, mapping, pagination, enrichment, derivation, retries.
- Modify `src/stonks/config.py` — remove Finnhub constants, add `YAHOO_ENRICHMENT_TTL_DAYS`, `YAHOO_PAGE_SIZE=250`, `YAHOO_MAX_WORKERS`.
- Modify `src/stonks/worker.py` — replace Finnhub phases with Yahoo screen + enrich + store; remove API-key gate.
- Modify `src/stonks/metrics.py` — delete Finnhub implementation; keep only shared normalization helpers used by the provider (or inline them into `yahoo.py` and delete the module).
- Modify `src/stonks/universe.py` — delete (universe now comes from the screener).
- Modify `src/stonks/app.py` — remove Finnhub footer/API-key copy; no filter UI changes.
- Modify `pyproject.toml`, `uv.lock`, `Dockerfile`, `docker-compose.yml`, `.env.example` (if present), `README.md`, `CHANGELOG.md`.
- Tests: replace `tests/test_metrics.py`, `tests/test_universe.py`, `tests/test_worker.py` with Yahoo equivalents; add `tests/test_yahoo.py`.

## Verification

- `uv run pytest -q` passes.
- `uv run ruff check src tests` passes.
- A live smoke script pages the screener and enriches one candidate, printing derived values; results are inspected manually.
- Applying each of the 9 presets against a freshly populated local DB returns rows that satisfy every filter in that preset.
