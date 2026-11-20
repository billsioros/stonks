# Yahoo Screener Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Finnhub with the free Yahoo Finance screener while preserving every existing preset filter, the SQLite store, and the Streamlit UI.

**Architecture:** A new `YahooProvider` owns all `yfinance` access. It pages the Yahoo screener with server-side predicates translated from Stonks filters, normalizes returned quote fields, then enriches only candidate symbols with cached per-symbol fundamentals and locally derived 5Y/10Y/15Y metrics. The worker persists rows to the existing `stocks` table; `SQLiteStore.get_stocks` remains the exact filter/sort authority.

**Tech Stack:** Python 3.12, `yfinance>=1.8.0`, Streamlit, SQLite, pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-11-20-yahoo-screener-migration-design.md`

## Global Constraints

- No API key, no paid tier, no stockanalysis.com scraping.
- Max 250 rows per Yahoo screener request (`yfinance` enforces this); paginate with `offset`.
- Stonks `market_cap`, `free_cash_flow`, `net_income` are in millions; Yahoo screener uses raw dollars.
- Derived columns that cannot be computed must be `NULL`, never fabricated.
- A failed Yahoo request must not delete or overwrite previously stored good data.
- `SQLiteStore.get_stocks` signature and behaviour do not change.
- All 9 `POPULAR_SCREENS` entries must remain applicable without editing the UI.
- Run all checks with `uv run` from `/home/vsioros/Desktop/stonks`.

## Review Focus

- **Yahoo caps pages at 250:** `test_paginate_fetches_all_pages` asserts offsets `[0, 250]` and 251 rows for a 251-row result.
- **Deep fields filter but are not returned:** `test_screen_does_not_read_missing_fundamentals` asserts no fundamental key is taken from the quote payload and enrichment is requested for every candidate.
- **Unit mismatches:** `test_normalize_quote_units` and `test_map_filter_units` pin market cap ×1e6, FCF/net income ÷1e6, and dividend yield identity.
- **New listings with short history:** `test_derive_metrics_insufficient_history` asserts `None` for all CAGRs/averages instead of a crash or zero.
- **Yahoo throttling/failure:** `test_enrich_preserves_cached_row_on_error` asserts an enrichment exception leaves the existing SQLite row intact and marks sync status failed.

---

### Task 1: Dependency and configuration groundwork

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/stonks/config.py`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: nothing.
- Produces: `YAHOO_PAGE_SIZE = 250`, `YAHOO_MAX_WORKERS = 8`, `YAHOO_ENRICHMENT_TTL_DAYS = 7` in `stonks.config`; `yfinance>=1.8.0` in dependencies.

- [ ] **Step 1: Add the dependency**

Add `yfinance>=1.8.0` to `[project].dependencies` in `pyproject.toml`. Keep `finnhub-python` for now (removed in Task 6).

- [ ] **Step 2: Add config constants**

In `src/stonks/config.py`, add exactly:

```python
YAHOO_PAGE_SIZE = 250
YAHOO_MAX_WORKERS = 8
YAHOO_ENRICHMENT_TTL_DAYS = 7
```

- [ ] **Step 3: Lock and verify import**

Run: `uv lock && uv run python -c "import yfinance; from stonks.config import YAHOO_PAGE_SIZE; print(yfinance.__version__, YAHOO_PAGE_SIZE)"`
Expected: prints `1.8.0 250` (or newer yfinance plus `250`).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock src/stonks/config.py
git commit -m "chore: add yfinance dependency and Yahoo config constants"
```

---

### Task 2: Screener query builder, pagination, and quote normalization

**Files:**
- Create: `src/stonks/yahoo.py`
- Test: `tests/test_yahoo.py`

**Interfaces:**
- Consumes: `YAHOO_PAGE_SIZE` from `stonks.config`; `yfinance.screen`, `yfinance.EquityQuery`.
- Produces:
  - `SCREENER_FIELD_MAP: dict[str, tuple[str, float]]`
  - `build_screener_query(filters: dict[str, dict]) -> EquityQuery`
  - `paginate(query: EquityQuery, page_size: int = YAHOO_PAGE_SIZE, screen_fn=...) -> list[dict]`
  - `normalize_quote(raw: dict) -> dict[str, object]`

- [ ] **Step 1: Write failing tests**

```python
def test_map_filter_units():
    q = build_screener_query({"market_cap": {"min": 1000}, "free_cash_flow": {"min": 1}})
    d = q.to_dict()
    assert {"operator": "GT", "operands": ["intradaymarketcap", 1000 * 1e6]} in d["operands"]
    assert {"operator": "GT", "operands": ["leveredfreecashflow.lasttwelvemonths", 1e6]} in d["operands"]

def test_build_query_always_restricts_to_us_equities():
    d = build_screener_query({}).to_dict()
    assert {"operator": "EQ", "operands": ["region", "us"]} in d["operands"]
    assert {"operator": "GT", "operands": ["intradaymarketcap", 0]} in d["operands"]

def test_build_query_skips_unmapped_columns():
    d = build_screener_query({"return_cagr_5y_pct": {"min": 10}}).to_dict()
    assert all("return_cagr_5y_pct" not in str(o) for o in d["operands"])

def test_paginate_fetches_all_pages(monkeypatch):
    calls = []
    def fake_screen(query, offset=None, size=None, **kwargs):
        calls.append(offset)
        end = min(offset + size, 251)
        return {"total": 251, "quotes": [{"symbol": f"S{i}", "marketCap": 1e9} for i in range(offset, end)]}
    monkeypatch.setattr("stonks.yahoo.screen", fake_screen)
    rows = paginate(build_screener_query({}), page_size=250, screen_fn=fake_screen)
    assert calls == [0, 250]
    assert len(rows) == 251

def test_normalize_quote_units():
    row = normalize_quote({"symbol": "ZTS", "shortName": "Zoetis", "exchange": "NYQ", "fullExchangeName": "NYSE",
                           "currency": "USD", "marketCap": 32_826_281_984, "regularMarketPrice": 80.79,
                           "trailingPE": 13.74, "priceToBook": 9.97, "bookValue": 8.106,
                           "dividendYield": 2.62, "epsTrailingTwelveMonths": 5.88,
                           "fiftyTwoWeekHigh": 132.49, "fiftyTwoWeekLow": 68.77,
                           "averageAnalystRating": "2.2 - Buy", "beta": 0.9})
    assert row["market_cap"] == pytest.approx(32826.281984)
    assert row["dividend_yield_pct"] == 2.62
    assert row["price"] == 80.79
    assert row["rating"] == "2.2 - Buy"
    assert row["pe_ratio"] == 13.74
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_yahoo.py -q`
Expected: collection error — `stonks.yahoo` does not exist.

- [ ] **Step 3: Implement the module skeleton and the three functions**

Create `src/stonks/yahoo.py`. Use `EquityQuery('and', ...)` with at least two operands (Yahoo rejects a single operand). Build the map from the spec's field table; convert each filter bound with the map's multiplier, `gt` for `min`, `lt` for `max`. `paginate` calls `screen_fn(query, offset=offset, size=page_size, sortField="ticker", sortAsc=False)` until fewer than `page_size` rows are returned or `total` is reached, then maps `normalize_quote` over all quotes. `normalize_quote` maps only the fields in the spec's quote table, returning `{}` for absent fields and `None` for derived columns it cannot supply.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yahoo.py -q`
Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/yahoo.py tests/test_yahoo.py
git commit -m "feat: add Yahoo screener query, pagination and quote normalization"
```

---

### Task 3: Fundamentals enrichment and derived metrics

**Files:**
- Modify: `src/stonks/yahoo.py`
- Modify: `tests/test_yahoo.py`

**Interfaces:**
- Consumes: `normalize_quote` output (`symbol` required).
- Produces:
  - `derive_metrics(info: dict | None, history, financials, balance_sheet, cashflow) -> dict[str, object]`
  - `enrich_symbol(symbol: str, ticker_factory=...) -> dict[str, object]`

- [ ] **Step 1: Write failing tests**

```python
def test_derive_metrics_cagr_and_averages():
    idx = pd.date_range("2011-01-31", "2026-01-31", freq="ME")
    history = pd.DataFrame({"Close": [100 * (1.1 ** (i / 12)) for i in range(len(idx))]}, index=idx)
    info = {"returnOnAssets": 0.10, "returnOnEquity": 0.20, "grossMargins": 0.5,
            "operatingMargins": 0.3, "debtToEquity": 150.0, "freeCashflow": 2e9,
            "heldPercentInsiders": 0.01, "dividendYield": 2.5}
    result = derive_metrics(info, history, None, None, None)
    assert result["return_cagr_5y_pct"] == pytest.approx(10.0, abs=0.2)
    assert result["roa_pct"] == 10.0
    assert result["roe_pct"] == 20.0
    assert result["debt_to_equity"] == pytest.approx(1.5)
    assert result["shares_insiders_pct"] == 0.01
    assert result["free_cash_flow"] == pytest.approx(2000.0)

def test_derive_metrics_insufficient_history():
    idx = pd.date_range("2025-01-31", periods=6, freq="ME")
    history = pd.DataFrame({"Close": range(100, 106)}, index=idx)
    result = derive_metrics({}, history, None, None, None)
    for key in ("return_cagr_5y_pct", "return_cagr_10y_pct", "return_cagr_15y_pct",
                "roa_5y_avg_pct", "roe_5y_avg_pct", "roic_5y_avg_pct"):
        assert result[key] is None

def test_enrich_symbol_handles_missing_ticker_data(monkeypatch):
    class FakeTicker:
        info = None
        def history(self, **kwargs): raise RuntimeError("no history")
    monkeypatch.setattr("stonks.yahoo.yf.Ticker", lambda symbol: FakeTicker())
    result = enrich_symbol("NEWCO")
    assert result["symbol"] == "NEWCO"
    assert result["free_cash_flow"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_yahoo.py -q`
Expected: `NameError`/`ImportError` for `derive_metrics` and `enrich_symbol`.

- [ ] **Step 3: Implement `derive_metrics` and `enrich_symbol`**

`derive_metrics`: convert `info` decimal fields to Stonks percent units (`×100`), `debtToEquity ÷100`, `freeCashflow ÷1e6`; compute CAGRs from month-end adjusted closes using index offsets of 60/120/180 months; return `None` when fewer points exist. Compute 5Y averages and growth CAGRs from annual statement DataFrames when provided, using up to 5 available columns and `None` when fewer than 2 points exist. `enrich_symbol`: construct `yf.Ticker(symbol)`, call `info`, `history(period="15y", interval="1mo", auto_adjust=True)`, `financials`, `balance_sheet`, `cashflow` inside individual try/except blocks, and pass whatever succeeded to `derive_metrics`; never propagate a Yahoo exception.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yahoo.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/yahoo.py tests/test_yahoo.py
git commit -m "feat: derive Stonks metrics from Yahoo fundamentals"
```

---

### Task 4: Preset candidate union and enrichment orchestration

**Files:**
- Modify: `src/stonks/yahoo.py`
- Modify: `tests/test_yahoo.py`

**Interfaces:**
- Consumes: `POPULAR_SCREENS` from `stonks.presets`; `build_screener_query`, `paginate`, `enrich_symbol`.
- Produces:
  - `preset_candidate_rows(presets: list[dict] = POPULAR_SCREENS, page_size: int = YAHOO_PAGE_SIZE, screen_fn=...) -> list[dict]`
  - `enrich_rows(rows: list[dict], required_columns: set[str], enrich_fn=...) -> list[dict]`

- [ ] **Step 1: Write failing tests**

```python
def test_preset_candidate_rows_deduplicates(monkeypatch):
    presets = [
        {"filters": {"market_cap": {"min": 1000}}},
        {"filters": {"roe_pct": {"min": 15}, "return_cagr_5y_pct": {"min": 10}}},
    ]
    seen = []
    def fake_screen(query, offset=None, size=None, **kwargs):
        seen.append(query.to_dict())
        symbols = ["AAA", "BBB"] if len(seen) == 1 else ["BBB", "CCC"]
        return {"total": len(symbols), "quotes": [{"symbol": s} for s in symbols]}
    rows = preset_candidate_rows(presets, page_size=250, screen_fn=fake_screen)
    assert [r["symbol"] for r in rows] == ["AAA", "BBB", "CCC"]
    assert len(seen) == 2

def test_enrich_rows_only_fetches_missing_columns(monkeypatch):
    calls = []
    def fake_enrich(symbol):
        calls.append(symbol)
        return {"roic_5y_avg_pct": 12.0}
    rows = [{"symbol": "AAA", "roic_5y_avg_pct": 9.0}, {"symbol": "BBB"}]
    result = enrich_rows(rows, {"roic_5y_avg_pct"}, enrich_fn=fake_enrich)
    assert calls == ["BBB"]
    assert result[0]["roic_5y_avg_pct"] == 9.0
    assert result[1]["roic_5y_avg_pct"] == 12.0

def test_screen_does_not_read_missing_fundamentals(monkeypatch):
    def fake_screen(query, offset=None, size=None, **kwargs):
        return {"total": 1, "quotes": [{"symbol": "AAA", "returnontotalcapital": 15}]}
    rows = preset_candidate_rows([{"filters": {"roic_pct": {"min": 10}}}], screen_fn=fake_screen)
    assert "roic_pct" not in rows[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_yahoo.py -q`
Expected: `NameError` for `preset_candidate_rows` and `enrich_rows`.

- [ ] **Step 3: Implement orchestration**

`preset_candidate_rows` builds one query per preset via `build_screener_query`, paginates each, and de-duplicates by `symbol` preserving first-seen order. `enrich_rows` computes `needed = required_columns - set(row)` per row, calls `enrich_fn(symbol)` only when `needed` is non-empty, merges the returned dict into the row, and isolates per-symbol exceptions (log and keep the original row).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yahoo.py -q`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/yahoo.py tests/test_yahoo.py
git commit -m "feat: derive preset candidate universe and enrich missing metrics"
```

---

### Task 5: Worker rewrite

**Files:**
- Modify: `src/stonks/worker.py`
- Modify: `tests/test_worker.py`

**Interfaces:**
- Consumes: `preset_candidate_rows`, `enrich_rows`, `derive_metrics` from `stonks.yahoo`; `SQLiteStore.save_stock`, `store.update_sync_status`, `store.get_stale_symbols`.
- Produces: `job()` with no API-key requirement; `required_preset_columns(presets=...) -> set[str]`.

- [ ] **Step 1: Write failing tests**

```python
def test_job_runs_without_api_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.setattr("stonks.worker.FINNHUB_API_KEY", "", raising=False)
    monkeypatch.setattr("stonks.worker.preset_candidate_rows", lambda **kw: [{"symbol": "AAA", "market_cap": 1000.0}])
    monkeypatch.setattr("stonks.worker.enrich_rows", lambda rows, **kw: rows)
    saved = []
    monkeypatch.setattr(SQLiteStore, "save_stock", lambda self, sym, data: saved.append((sym, data)))
    monkeypatch.setattr(SQLiteStore, "update_sync_status", lambda *a, **kw: None)
    monkeypatch.setattr(SQLiteStore, "get_stale_symbols", lambda *a, **kw: [])
    job()
    assert saved and saved[0][0] == "AAA"

def test_enrich_preserves_cached_row_on_error(monkeypatch):
    def boom(rows, **kwargs): raise RuntimeError("Yahoo 429")
    monkeypatch.setattr("stonks.worker.enrich_rows", boom)
    monkeypatch.setattr("stonks.worker.preset_candidate_rows", lambda **kw: [{"symbol": "AAA", "price": 1.0}])
    monkeypatch.setattr(SQLiteStore, "update_sync_status", lambda *a, **kw: statuses.append(a))
    statuses = []
    monkeypatch.setattr(SQLiteStore, "save_stock", lambda *a, **kw: None)
    job()  # must not raise
    assert any(s[0] == "AAA" and s[2] == "failed" for s in statuses)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_worker.py -q`
Expected: failures because `job()` still references Finnhub and API key.

- [ ] **Step 3: Rewrite `job()`**

Remove the Finnhub key check, `UniverseLoader`, `MetricsProvider`, and the four Finnhub phases. New flow:
1. `rows = preset_candidate_rows()`; log count and `store.save_metadata("universe_size", len(rows))`.
2. Select symbols needing enrichment: those not in `store.get_synced_symbols("fundamentals")` or in `store.get_stale_symbols("fundamentals", stale_hours=YAHOO_ENRICHMENT_TTL_DAYS * 24)`.
3. `enrich_rows([r for r in rows if r["symbol"] in targets], required_preset_columns())` inside try/except; on failure log and mark each target `failed` via `store.update_sync_status`, then continue with unenriched rows.
4. For each row, call `store.save_stock(symbol, row)` and `store.update_sync_status(symbol, "fundamentals", "success", None)`. Save quote-only rows even when enrichment fails, so browsing still works.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_worker.py -q`
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/worker.py tests/test_worker.py
git commit -m "feat: run worker from Yahoo screener candidates"
```

---

### Task 6: Remove Finnhub and update app/docs

**Files:**
- Delete: `src/stonks/metrics.py`, `src/stonks/universe.py`
- Delete: `tests/test_metrics.py`, `tests/test_universe.py`
- Modify: `src/stonks/app.py`
- Modify: `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `README.md`, `CHANGELOG.md`
- Modify: `.env` (remove the key locally only if the user confirms; otherwise leave the untracked file untouched)

**Interfaces:**
- Consumes: nothing new.
- Produces: a repo with no `finnhub` imports or env references.

- [ ] **Step 1: Assert current references**

Run: `grep -RIn "finnhub\|FINNHUB" --exclude-dir=.git --exclude-dir=.venv --exclude=uv.lock .`
Expected: matches only in the files listed above plus `uv.lock` and possibly `.env`.

- [ ] **Step 2: Delete dead modules and tests**

Remove `src/stonks/metrics.py`, `src/stonks/universe.py`, `tests/test_metrics.py`, `tests/test_universe.py` with `rm`. Do not touch `.env`.

- [ ] **Step 3: Remove dependency and env wiring**

Remove `finnhub-python` from `pyproject.toml`, `FINNHUB_API_KEY` from `Dockerfile` and `docker-compose.yml`, and any Finnhub credits/API-key copy from `src/stonks/app.py`, `README.md`, and `CHANGELOG.md`. Replace with Yahoo Finance attribution.

- [ ] **Step 4: Regenerate lock and verify no references**

Run: `uv lock && grep -RIn "finnhub\|FINNHUB" --exclude-dir=.git --exclude-dir=.venv --exclude=.env .`
Expected: no output except historical CHANGELOG entries if deliberately retained as release notes.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove Finnhub integration and update attribution"
```

---

### Task 7: Full verification and live smoke

**Files:**
- No source changes expected; fix any failures in the owning task's files.

**Interfaces:**
- Consumes: the complete implementation.
- Produces: a verified working tree.

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass, no skips caused by missing API keys.

- [ ] **Step 2: Run lint**

Run: `uv run ruff check src tests`
Expected: no errors.

- [ ] **Step 3: Live smoke (no network writes to external services)**

Run:

```bash
uv run python - <<'PY'
from stonks.yahoo import preset_candidate_rows, enrich_symbol
rows = preset_candidate_rows([{"filters": {"market_cap": {"min": 50000}}}], page_size=5)
print("candidates:", len(rows), rows[0]["symbol"])
print("enriched:", {k: v for k, v in enrich_symbol(rows[0]["symbol"]).items() if k in ("market_cap", "roe_pct", "return_cagr_5y_pct")})
PY
```

Expected: at least one candidate and a dict containing `market_cap`; derived keys may be `None` only if Yahoo lacks data.

- [ ] **Step 4: Preset correctness check against local DB**

Run a short script that, for each of the 9 `POPULAR_SCREENS`, calls `SQLiteStore().get_stocks(filters=preset["filters"], page=1, page_size=5)` after a worker run and asserts every returned row satisfies each min/max in that preset. Expected: no violations.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A && git commit -m "test: verify Yahoo migration end to end"
```
