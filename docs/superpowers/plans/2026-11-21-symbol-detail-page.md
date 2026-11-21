# Symbol Detail Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking a symbol anywhere in the screener opens an in-app detail page (Overview, Financials, Statistics, Metrics, Forecast) backed by live StockAnalysis per-symbol payloads.

**Architecture:** A fetch/resolve/cache layer (`detail.py`) turns SvelteKit `__data.json` payloads into plain Python, a pure parser module (`detail_parse.py`) turns them into display structures, and a Streamlit module (`detail_view.py`) renders five tabs. `app.py` only gains page state, row selection and a back control. Cache lives in the existing `kv_cache` table.

**Tech Stack:** Python 3.12, Streamlit 1.56, SQLite (stdlib), pandas; `uv` for all commands.

**Spec:** `docs/superpowers/specs/2026-11-21-symbol-detail-page-and-alerts-design.md` (Phase A only; Phase B — alerts/news — gets its own plan).

## Global Constraints

- Missing provider data renders `—`; never fabricate, never carry a value across periods.
- The `"[PRO]"` sentinel and any other non-numeric string render `—`.
- Use `uv run` for every Python command.
- `uv run pytest -q` and `uv run ruff check src tests` must pass; `uv run ruff format --check src tests` must be clean.
- `uv.lock` is never staged or committed.
- Work stays on `feature/yahoo-migration-minors`; no push.
- StockAnalysis requests go through `stonks.stockanalysis.fetch_json` with its existing UA/retry/timeout; no new dependency.
- Per-symbol cache keys are `sym:{SYMBOL}:{page}:{statement}:{period}`; TTL 900s for overview/statistics/forecast, 86400s for financials.
- Existing look only: indigo accent `#6366f1`, `.sk-*` classes, `section-header`, 44px table rows.

## Review Focus

1. A ratio or EPS row whose payload value is the string `"[PRO]"` — must show `—`, never `PRO` and never raise in number formatting.
2. A line item with fewer values than the period list (provider trims history) — must pad with `—` rather than shifting values onto the wrong fiscal year.
3. A symbol with no StockAnalysis page (e.g. `ZZZZ`) — must show `No data for ZZZZ` plus the back control, not a blank page or traceback.
4. One of the five per-page fetches failing while others succeed — only that tab shows an error card; the rest still render.
5. Returning to the screener must preserve filters, view preset, sort and page number exactly as they were.

---

### Task 1: Cache accessors on SQLiteStore

**Files:**
- Modify: `src/stonks/store.py` (add methods after `get_metadata`, ~line 426)
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: existing `self._connect()`, `kv_cache(key, value, expires_at)` table.
- Produces: `cache_get(self, key: str) -> Any | None`, `cache_set(self, key: str, value: Any, ttl_seconds: float) -> None`, `cache_delete(self, key: str) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_cache_roundtrip(store):
    store.cache_set("sym:NVDA:overview:-:annual", {"a": [1, 2]}, ttl_seconds=60)
    assert store.cache_get("sym:NVDA:overview:-:annual") == {"a": [1, 2]}

def test_cache_missing_returns_none(store):
    assert store.cache_get("nope") is None

def test_cache_expired_returns_none(store):
    store.cache_set("k", {"a": 1}, ttl_seconds=-1)
    assert store.cache_get("k") is None

def test_cache_delete_removes_entry(store):
    store.cache_set("k", {"a": 1}, ttl_seconds=60)
    store.cache_delete("k")
    assert store.cache_get("k") is None

def test_cache_overwrite_replaces_value(store):
    store.cache_set("k", {"a": 1}, ttl_seconds=60)
    store.cache_set("k", {"a": 2}, ttl_seconds=60)
    assert store.cache_get("k") == {"a": 2}
```

Add a `store` fixture if absent (existing tests build `SQLiteStore(tmp_path / "t.db")` inline; follow that).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_store.py -k cache -v`
Expected: FAIL — `SQLiteStore` has no attribute `cache_set`.

- [ ] **Step 3: Implement**

`cache_set` writes `json.dumps(value)` with `expires_at = time.time() + ttl_seconds` using `ON CONFLICT(key) DO UPDATE`. `cache_get` selects `value, expires_at`, returns `None` when the row is missing, expired, or the JSON does not decode. `cache_delete` deletes by key. All three commit.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_store.py -q`
Expected: all pass, including the 5 new ones.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/store.py tests/test_store.py
git commit -m "feat(store): add kv_cache accessors for per-symbol page cache"
```

---

### Task 2: Payload resolution, URLs and cached loading

**Files:**
- Create: `src/stonks/detail.py`
- Create: `tests/fixtures/` (recorded payloads)
- Test: `tests/test_detail.py`

**Interfaces:**
- Consumes: `stonks.store.SQLiteStore.cache_get/cache_set/cache_delete`, `stonks.stockanalysis.fetch_json`.
- Produces:
  - `PAGES = ("overview", "statistics", "forecast", "financials")`
  - `STATEMENTS = ("income-statement", "balance-sheet", "cash-flow-statement", "ratios")`
  - `CACHE_TTL_SECONDS: dict[str, float]`
  - `page_url(symbol: str, page: str, *, statement: str = "income-statement", quarterly: bool = False) -> str`
  - `cache_key(symbol: str, page: str, *, statement: str = "income-statement", period: str = "annual") -> str`
  - `resolve_payload(payload: Any) -> Any`
  - `load_page(store, symbol: str, page: str, *, statement: str = "income-statement", period: str = "annual", force: bool = False, fetch: Callable[[str], Any] | None = None) -> tuple[Any | None, float | None]` returning `(resolved_root, fetched_at_epoch)`.

- [ ] **Step 1: Record fixtures**

```bash
uv run python - <<'PY'
import urllib.request
from pathlib import Path
UA = {"User-Agent": "Mozilla/5.0 (compatible; stonks)"}
base = "https://stockanalysis.com/stocks/nvda/"
pages = {
    "nvda_overview": base + "__data.json",
    "nvda_statistics": base + "statistics/__data.json",
    "nvda_forecast": base + "forecast/__data.json",
    "nvda_income_annual": base + "financials/income-statement/__data.json",
    "nvda_income_quarterly": base + "financials/income-statement/__data.json?p=quarterly",
    "nvda_balance_annual": base + "financials/balance-sheet/__data.json",
}
out = Path("tests/fixtures"); out.mkdir(parents=True, exist_ok=True)
for name, url in pages.items():
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        (out / f"{name}.json").write_bytes(r.read())
    print(name, "ok")
PY
```

Confirm all six files landed and the directory totals under 200 KiB (measured 123 KiB on 2026-11-21). Fixtures are frozen provider snapshots: never regenerate them to make a test pass.

- [ ] **Step 2: Write the failing resolver tests**

```python
def _payload(values):
    return {"type": "data", "nodes": [{}, {}, {"data": values}]}

def test_resolve_payload_dereferences_indices():
    assert resolve_payload(_payload([{"price": 1, "name": 2}, 42.5, "NVDA"])) == {
        "price": 42.5, "name": "NVDA"
    }

def test_resolve_payload_keeps_literal_ints():
    # index 1 holds the literal 41; it must not be dereferenced again.
    assert resolve_payload(_payload([{"count": 1}, 41])) == {"count": 41}

def test_resolve_payload_maps_negative_and_out_of_range_to_none():
    assert resolve_payload(_payload([{"a": -1, "b": 9}, 1])) == {"a": None, "b": None}

def test_resolve_payload_breaks_cycles():
    assert resolve_payload(_payload([{"self": 1}, {"parent": 1}])) == {
        "self": {"parent": None}
    }

def test_resolve_payload_rejects_non_data_payload():
    assert resolve_payload({"type": "error"}) is None
    assert resolve_payload({}) is None
    assert resolve_payload({"type": "data", "nodes": []}) is None
```

- [ ] **Step 3: Write the failing URL/cache-key tests**

```python
def test_page_url_overview():
    assert page_url("NVDA", "overview") == "https://stockanalysis.com/stocks/nvda/__data.json"

def test_page_url_statistics():
    assert page_url("nvda", "statistics") == (
        "https://stockanalysis.com/stocks/nvda/statistics/__data.json"
    )

def test_page_url_financials_quarterly_statement():
    assert page_url("NVDA", "financials", statement="ratios", quarterly=True) == (
        "https://stockanalysis.com/stocks/nvda/financials/ratios/__data.json?p=quarterly"
    )

def test_cache_key_includes_statement_and_period():
    assert cache_key("NVDA", "financials", statement="ratios", period="quarterly") == (
        "sym:NVDA:financials:ratios:quarterly"
    )
    assert cache_key("NVDA", "overview") == "sym:NVDA:overview:-:annual"
```

- [ ] **Step 4: Write the failing load_page tests**

```python
def test_load_page_fetches_then_caches(store):
    calls = []
    def fetch(url):
        calls.append(url)
        return _payload([{"marketCap": 1}, "3.03T"])
    data, at = load_page(store, "NVDA", "overview", fetch=fetch)
    assert data == {"marketCap": "3.03T"} and at is not None
    data2, at2 = load_page(store, "NVDA", "overview", fetch=fetch)
    assert data2 == data and at2 == at and len(calls) == 1

def test_load_page_force_refetches(store):
    payload = _payload([{"marketCap": 1}, "3.03T"])
    calls = []
    def fetch(url):
        calls.append(url); return payload
    load_page(store, "NVDA", "overview", fetch=fetch)
    load_page(store, "NVDA", "overview", force=True, fetch=fetch)
    assert len(calls) == 2

def test_load_page_falls_back_to_stale_cache_on_failure(store):
    store.cache_set(
        "sym:NVDA:overview:-:annual",
        {"data": {"marketCap": "3.03T"}, "fetched_at": 1234.0},
        ttl_seconds=-1,
    )
    def boom(url):
        raise OSError("down")
    assert load_page(store, "NVDA", "overview", fetch=boom) == ({"marketCap": "3.03T"}, 1234.0)

def test_load_page_returns_none_without_cache_on_failure(store):
    def boom(url):
        raise OSError("down")
    assert load_page(store, "ZZZZ", "overview", fetch=boom) == (None, None)
```

- [ ] **Step 5: Run to verify failure**

Run: `uv run pytest tests/test_detail.py -v`
Expected: FAIL — `ModuleNotFoundError: stonks.detail`.

- [ ] **Step 6: Implement `src/stonks/detail.py`**

Resolution is the only piece whose algorithm the tests do not fully determine, so it is spelled out:

```python
def resolve_payload(payload):
    if not isinstance(payload, dict) or payload.get("type") != "data":
        return None
    nodes = payload.get("nodes") or []
    if len(nodes) < 3 or not isinstance(nodes[2], dict):
        return None
    array = nodes[2].get("data")
    if not isinstance(array, list) or not array:
        return None
    memo: dict[int, Any] = {}

    def value_at(index, stack):
        if not isinstance(index, int) or index < 0 or index >= len(array):
            return None
        if index in memo:
            return memo[index]
        if index in stack:
            return None
        raw = array[index]
        if not isinstance(raw, (dict, list)):
            memo[index] = raw           # a literal (number/string/bool/null)
            return raw
        out = walk(raw, stack + (index,))
        memo[index] = out
        return out

    def walk(node, stack):
        if isinstance(node, dict):
            return {key: walk(child, stack) for key, child in node.items()}
        if isinstance(node, list):
            return [walk(child, stack) for child in node]
        if isinstance(node, bool) or node is None:
            return node
        if isinstance(node, int):
            return value_at(node, stack)
        return node

    return value_at(0, ())
```

`walk` must be defined before `value_at` uses it (define `walk` first, or nest `value_at`/`walk` with `walk` declared above). `page_url` lowercases the symbol and appends `__data.json` with `?p=quarterly` for quarterly financials, defaulting to the annual path otherwise. `load_page` reads the cache unless `force`, calls `(fetch or fetch_json)(url)`, resolves, and stores `{"data": resolved, "fetched_at": now}` with `CACHE_TTL_SECONDS[page]`; on exception it returns any cached copy (even expired) and `(None, None)` when there is none. Successful empty resolution is treated as a failure, not cached.

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_detail.py -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/stonks/detail.py tests/test_detail.py tests/fixtures
git commit -m "feat(detail): resolve and cache per-symbol StockAnalysis payloads"
```

---

### Task 3: Parse the overview payload

**Files:**
- Create: `src/stonks/detail_parse.py`
- Test: `tests/test_detail_parse.py`

**Interfaces:**
- Consumes: `resolve_payload` output (a dict).
- Produces: `parse_overview(data: dict[str, Any]) -> dict[str, Any]` with keys `market_cap`, `pe_ratio`, `forward_pe`, `eps`, `revenue`, `revenue_type`, `revenue_growth`, `net_income`, `net_income_growth`, `shares_out`, `beta`, `dividend`, `ex_dividend_date`, `analyst_rating`, `analyst_target`, `earnings_date`, `earnings_date_label`, `summary`, `info` (list of `{"label","value","url"}`), `news` (list of `{"title","url","source","ago","summary"}`).

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path
FIXTURES = Path(__file__).parent / "fixtures"

def _load(name):
    return resolve_payload(json.loads((FIXTURES / f"{name}.json").read_text()))

def test_parse_overview_fields():
    out = parse_overview(_load("nvda_overview"))
    assert out["market_cap"] == "3.03T"
    assert out["analyst_rating"] == "Buy"
    assert out["analyst_target"] == "244.18 (+94.52%)"
    assert out["summary"].startswith("NVIDIA Corporation operates")

def test_parse_overview_info_rows_become_absolute_urls():
    out = parse_overview(_load("nvda_overview"))
    assert out["info"][0] == {
        "label": "Industry",
        "value": "Semiconductors",
        "url": "https://stockanalysis.com/stocks/industry/semiconductors",
    }

def test_parse_overview_news_items():
    news = parse_overview(_load("nvda_overview"))["news"]
    assert 1 <= len(news) <= 10
    assert set(news[0]) == {"title", "url", "source", "ago", "summary"}
    assert news[0]["url"].startswith("https://")

def test_parse_overview_missing_fields_are_none():
    out = parse_overview({})
    assert out["market_cap"] is None and out["news"] == [] and out["info"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_detail_parse.py -q`
Expected: FAIL — module or name not found.

- [ ] **Step 3: Implement `parse_overview`**

Read the keys straight off the payload root; absent keys become `None`. `infoTable` rows (`{"t","v","u"}`) map to `{"label": t, "value": v, "url": "https://stockanalysis.com/" + u if u else None}`. `news["data"]` entries map `text`→`summary` and drop the rest; cap at 10 items. Never invent a missing field.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_detail_parse.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/detail_parse.py tests/test_detail_parse.py
git commit -m "feat(detail): parse overview payload into quote, info and news"
```

---

### Task 4: Parse the statistics payload

**Files:**
- Modify: `src/stonks/detail_parse.py`
- Test: `tests/test_detail_parse.py`

**Interfaces:**
- Produces: `STATISTICS_ORDER: tuple[tuple[str, str], ...]` — `(key, title)` pairs such as `("valuation", "Valuation")`, `("evRatios", "EV Ratios")`, `("financialPosition", "Financial Position")`, `("financialEfficiency", "Financial Efficiency")`, `("stockPrice", "Stock Price")`, `("shortSelling", "Short Selling")`, `("analystForecasts", "Analyst Forecasts")`, `("fairValue", "Fair Value")`; and `parse_statistics(data: dict[str, Any]) -> list[dict[str, Any]]` returning `[{"key","title","text","items":[{"id","title","value","hover"}]}]` in `STATISTICS_ORDER` order, skipping sections the payload omits or that have no items.

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_statistics_order_and_shape():
    sections = parse_statistics(_load("nvda_statistics"))
    assert [s["key"] for s in sections][:3] == ["valuation", "dates", "shares"]
    assert sections[0]["title"] == "Valuation"
    assert sections[0]["items"][0] == {
        "id": "marketcap",
        "title": "Market Cap",
        "value": "3.03T",
        "hover": "3,031,172,910,000",
    }

def test_parse_statistics_covers_every_present_section():
    keys = {s["key"] for s in parse_statistics(_load("nvda_statistics"))}
    assert {"valuation", "ratios", "evRatios", "financialPosition", "margins",
            "dividends", "shortSelling", "scores", "fairValue"} <= keys

def test_parse_statistics_empty_payload():
    assert parse_statistics({}) == []
    assert parse_statistics({"valuation": {"data": []}}) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_detail_parse.py -k statistics -v`
Expected: FAIL — `parse_statistics` not defined.

- [ ] **Step 3: Implement**

Use the section titles from `STATISTICS_ORDER` (the payload carries no titles); `text` is the section's sentence; each item keeps `id`, `title`, `value`, `hover`, with missing values as `None`. Sections not in `STATISTICS_ORDER` are ignored.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_detail_parse.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/detail_parse.py tests/test_detail_parse.py
git commit -m "feat(detail): parse statistics payload into titled sections"
```

---

### Task 5: Parse the forecast payload

**Files:**
- Modify: `src/stonks/detail_parse.py`
- Test: `tests/test_detail_parse.py`

**Interfaces:**
- Produces: `parse_forecast(data: dict[str, Any]) -> dict[str, Any]` with keys:
  - `targets`: `{"low","median","average","high","count","updated"} | None` (top-level only; ignore the horizon-specific `filtered` map)
  - `estimates`: `{"annual": {...}, "quarterly": {...}}`, each `{"epsThis","epsNext","revenueThis","revenueNext"}` → `{"last","this","growth"}`
  - `current_ratings`: `{"consensus","score","count","strongBuy","buy","hold","sell","strongSell"} | None`
  - `recommendations`: list of the monthly consensus records (source dicts, `buy/hold/sell/strongBuy/strongSell/total/consensus/month`)
  - `ratings`: list of `{"firm","analyst","action","target_now","target_old","rating_new","rating_old","date","time"}`

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_forecast_targets():
    out = parse_forecast(_load("nvda_forecast"))
    assert out["targets"] == {
        "low": 130, "median": 230, "average": 240.51, "high": 425,
        "count": 41, "updated": "2026-11-19",
    }

def test_parse_forecast_estimates_and_ratings_summary():
    out = parse_forecast(_load("nvda_forecast"))
    assert out["estimates"]["annual"]["epsThis"]["growth"] == pytest.approx(102.70964360587004)
    assert out["current_ratings"]["consensus"] == "Buy"
    assert out["current_ratings"]["count"] == 63

def test_parse_forecast_analyst_actions():
    action = parse_forecast(_load("nvda_forecast"))["ratings"][0]
    assert action["firm"] == "Wedbush"
    assert action["action"] == "Reiterates"
    assert action["target_now"] == 293 and action["target_old"] == 275
    assert action["rating_new"] == "Buy"

def test_parse_forecast_empty_payload():
    out = parse_forecast({})
    assert out["targets"] is None
    assert out["current_ratings"] is None
    assert out["ratings"] == [] and out["recommendations"] == []
    assert out["estimates"] == {"annual": {}, "quarterly": {}}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_detail_parse.py -k forecast -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Map `pt_now`→`target_now`, `pt_old`→`target_old`, `action_rt`→`action`, dropping `scores`/`slug`. Keep numbers as sent; do not reformat.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_detail_parse.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/detail_parse.py tests/test_detail_parse.py
git commit -m "feat(detail): parse forecast payload into targets, estimates and ratings"
```

---

### Task 6: Parse financial statements (annual and quarterly)

**Files:**
- Modify: `src/stonks/detail_parse.py`
- Test: `tests/test_detail_parse.py`

**Interfaces:**
- Produces: `parse_statement(data: dict[str, Any]) -> dict[str, Any]` with
  - `periods`: `[{"key": "TTM"|"2026-01-25", "label": "TTM"|"FY2026"|"Q3 2026", "is_ttm": bool}]`
  - `rows`: `[{"id": "operatingRevenue", "label": "Operating Revenue", "values": [float | None, ...]}]` — one value per period, always the same length as `periods`, in `map` order
  - `statement`, `period` (echoed from the payload).

- [ ] **Step 1: Write the failing tests**

```python
def test_parse_statement_annual_periods_and_rows():
    st = parse_statement(_load("nvda_income_annual"))
    assert st["periods"][0] == {"key": "TTM", "label": "TTM", "is_ttm": True}
    assert st["periods"][1]["label"] == "FY2026"
    assert st["periods"][1]["is_ttm"] is False
    assert len(st["rows"]) == 53
    assert st["rows"][0]["label"] == "Operating Revenue"
    assert len(st["rows"][0]["values"]) == len(st["periods"])

def test_parse_statement_quarterly_labels():
    st = parse_statement(_load("nvda_income_quarterly"))
    assert st["periods"][0]["key"] == "2026-10-25"
    assert st["periods"][0]["label"].startswith("Q")
    assert all(not p["is_ttm"] for p in st["periods"])

def test_parse_statement_pro_sentinel_becomes_none():
    payload = {"financialData": {"datekey": ["TTM", "2026-01-25"], "fiscalYear": [None, "2026"],
                                 "fiscalQuarter": [None, None], "revenue": [100, "[PRO]"]},
               "map": [{"id": "revenue", "title": "Revenue"}],
               "statement": "income-statement", "period": "annual"}
    st = parse_statement(payload)
    assert st["rows"][0] == {"id": "revenue", "label": "Revenue", "values": [100, None]}

def test_parse_statement_pads_short_line_items():
    payload = {"financialData": {"datekey": ["TTM", "2026-01-25"], "fiscalYear": [None, "2026"],
                                 "fiscalQuarter": [None, None], "revenue": [100]},
               "map": [{"id": "revenue", "title": "Revenue"}],
               "statement": "income-statement", "period": "annual"}
    assert parse_statement(payload)["rows"][0]["values"] == [100, None]

def test_parse_statement_empty_payload():
    st = parse_statement({})
    assert st["periods"] == [] and st["rows"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_detail_parse.py -k statement -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Annual labels: `TTM` for the TTM key, else `f"FY{year}"` from the aligned `fiscalYear` entry (fall back to the `datekey` year when `fiscalYear` is null). Quarterly labels: `f"{fiscalQuarter} {fiscalYear}"`, falling back to the `datekey` when either is null. Values: take `financialData[id]`, truncate or pad with `None` to `len(periods)`; keep `int`/`float`; map `"[PRO]"` and any other non-numeric value to `None`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_detail_parse.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/detail_parse.py tests/test_detail_parse.py
git commit -m "feat(detail): parse annual and quarterly financial statements"
```

---

### Task 7: Shared formatting and the Overview tab

**Files:**
- Create: `src/stonks/detail_view.py`
- Test: `tests/test_detail_view.py`

**Interfaces:**
- Consumes: `detail.load_page`, `detail_parse.parse_overview`, `detail_parse.parse_statistics`.
- Produces:
  - `format_compact(value: Any) -> str` — `—` for `None`/`"[PRO]"`/empty; `361.81B`, `2.50M`, `12.40K` for large magnitudes; plain `3.33` otherwise.
  - `format_cell(value: Any) -> str` — `—` for `None`/`"[PRO]"`/empty string; strings pass through; numbers go through `format_compact`.
  - `range_position(price: float | None, low: float | None, high: float | None) -> float | None` — 0..1 position in the 52-week range, `None` when any input is `None` or `low >= high`.
  - `yoy_pct(current: float | None, prior: float | None) -> float | None` — percent change, `None` when either is `None` or `prior == 0`.
  - `render_detail_page(store: SQLiteStore, symbol: str) -> None`

- [ ] **Step 1: Write the failing tests**

```python
def test_format_compact_scales_large_numbers():
    assert format_compact(361_808_000_000) == "361.81B"
    assert format_compact(2_500_000) == "2.50M"
    assert format_compact(12_400) == "12.40K"
    assert format_compact(3.33) == "3.33"

def test_format_cell_handles_missing_and_pro():
    assert format_cell(None) == "—"
    assert format_cell("[PRO]") == "—"
    assert format_cell("") == "—"
    assert format_cell("S&P Global") == "S&P Global"

def test_range_position():
    assert range_position(100, 50, 150) == pytest.approx(0.5)
    assert range_position(None, 50, 150) is None
    assert range_position(100, 150, 50) is None

def test_yoy_pct():
    assert yoy_pct(110, 100) == pytest.approx(10.0)
    assert yoy_pct(100, 0) is None
    assert yoy_pct(None, 100) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_detail_view.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the helpers and `render_detail_page` skeleton**

`render_detail_page` loads the overview payload once, renders a header with the store row (symbol, company name from `stocks.description`, price, 52-week range via `range_position`), the signal strip (analyst rating, target upside, DCF upside, Lynch upside, short %, from the store row; `—` when null), the news block (first 5 items, each a markdown link with source and `ago`), and `st.tabs(["Overview","Financials","Statistics","Metrics","Forecast"])` where every non-Overview tab body is a placeholder for Tasks 8–9. On `(None, None)` render `st.error(f"No data for {symbol}")` and return. Show an `as of HH:MM` caption and a `🔄 Refresh` button that calls `store.cache_delete` for the page keys and reruns.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_detail_view.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/detail_view.py tests/test_detail_view.py
git commit -m "feat(detail): render overview tab with signals and headlines"
```

---

### Task 8: Financials tab

**Files:**
- Modify: `src/stonks/detail_view.py`
- Test: `tests/test_detail_view.py`

**Interfaces:**
- Consumes: `detail.load_page(..., page="financials", statement=..., period=...)`, `detail_parse.parse_statement`, `yoy_pct`.
- Produces: `_render_financials(store: SQLiteStore, symbol: str) -> None` and a pure helper `statement_frame(statement: dict[str, Any], *, show_growth: bool) -> tuple[list[str], list[list[str]]]` returning `(column_labels, rows)` of already-formatted strings, with the growth column appended last when `show_growth` is true.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_detail_view.py opens with the same fixture helper used by the parser tests:
#   FIXTURES = Path(__file__).parent / "fixtures"
#   def _load(name): return resolve_payload(json.loads((FIXTURES / f"{name}.json").read_text()))

def test_statement_frame_columns_and_cells():
    st = parse_statement(_load("nvda_income_annual"))
    labels, rows = statement_frame(st, show_growth=False)
    assert labels[0] == "" and labels[1] == "TTM" and labels[2] == "FY2026"
    assert rows[0][0] == "Operating Revenue"
    assert len(rows[0]) == len(labels)

def test_statement_frame_growth_column():
    st = {"periods": [{"key": "2026-01-25", "label": "FY2026", "is_ttm": False},
                      {"key": "2025-01-26", "label": "FY2025", "is_ttm": False}],
          "rows": [{"id": "revenue", "label": "Revenue", "values": [110.0, 100.0]},
                   {"id": "gp", "label": "Gross Profit", "values": [None, 100.0]}]}
    labels, rows = statement_frame(st, show_growth=True)
    assert labels[-1] == "YoY"
    assert rows[0][-1] == "+10.00%"
    assert rows[1][-1] == "—"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_detail_view.py -k statement_frame -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

`statement_frame` builds `[""] + [p["label"] for p in periods]` (+ `"YoY"`), formats each value with `format_compact`, and appends `yoy_pct(values[0], values[1])` formatted as `+10.00%` / `-4.00%` / `—`. `_render_financials` renders four `st.tabs` (Income Statement, Balance Sheet, Cash Flow, Ratios), each with an `Annual`/`Quarterly` `st.radio` (`horizontal=True`, keys `fin_period_{statement}`) and a `Growth` toggle, loads via `load_page`, and renders `st.dataframe(pd.DataFrame(rows, columns=labels), hide_index=True, row_height=44, width="stretch")`. A failed load shows `st.error("Could not load …")` in that statement tab only.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_detail_view.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/detail_view.py tests/test_detail_view.py
git commit -m "feat(detail): render financials tab with annual/quarterly and growth"
```

---

### Task 9: Statistics, Metrics and Forecast tabs

**Files:**
- Modify: `src/stonks/detail_view.py`
- Test: `tests/test_detail_view.py`

**Interfaces:**
- Consumes: `detail_parse.parse_statistics`, `detail_parse.parse_forecast`, `format_cell`, `STATISTICS_ORDER`.
- Produces: `_render_statistics(store, symbol)`, `_render_metrics(store, symbol)`, `_render_forecast(store, symbol)`, and a pure `metrics_sections(sections: list[dict]) -> list[dict]` selecting `ratios`, `margins`, `evRatios`, `shares` for the Metrics tab.

- [ ] **Step 1: Write the failing tests**

```python
def test_metrics_sections_selects_ratio_groups():
    sections = parse_statistics(_load("nvda_statistics"))
    keys = [s["key"] for s in metrics_sections(sections)]
    assert keys == ["ratios", "evRatios", "margins", "shares"]

def test_metrics_sections_tolerates_missing_groups():
    assert metrics_sections([{"key": "valuation", "title": "Valuation", "text": "", "items": []}]) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_detail_view.py -k metrics -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Statistics tab renders every section from `parse_statistics` as a card with `section-header`, the section `text`, and a two-column `st.dataframe` of title/value. Metrics uses `metrics_sections`. Forecast renders targets (low/median/average/high/count/updated), the `current_ratings` consensus with counts, `estimates` for annual and quarterly (this year / next year / growth), and `ratings` as a table of firm, analyst, action, target now/old, rating, date. Every missing value goes through `format_cell`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_detail_view.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/detail_view.py tests/test_detail_view.py
git commit -m "feat(detail): render statistics, metrics and forecast tabs"
```

---

### Task 10: Navigation from screener and watchlist

**Files:**
- Modify: `src/stonks/app.py` (`_init_session_state` ~1252, `render_screener_table` ~766, `render_watchlist_tab` ~988, `main` ~1267)
- Test: `tests/test_navigation.py`

**Interfaces:**
- Produces: session keys `page` (`"screener"` default) and `detail_symbol` (`None` default); `open_symbol(symbol: str) -> None` and `close_detail() -> None` in `app.py`.

- [ ] **Step 1: Write the failing AppTest cases**

```python
from streamlit.testing.v1 import AppTest

def _app():
    at = AppTest.from_file("src/stonks/app.py", default_timeout=120)
    at.run()
    return at

def test_detail_page_without_data_shows_error_and_back():
    at = _app()
    at.session_state["page"] = "detail"
    at.session_state["detail_symbol"] = "ZZZZ"
    at.run()
    assert not at.exception
    assert any("No data for ZZZZ" in str(e.value) for e in at.error)

def test_back_control_restores_screener_and_filters():
    at = _app()
    before = dict(at.session_state["active_filters"])
    at.session_state["page"] = "detail"
    at.session_state["detail_symbol"] = "ZZZZ"
    at.run()
    back = next(b for b in at.button if "Back" in b.label)
    back.click().run()
    assert at.session_state["page"] == "screener"
    assert dict(at.session_state["active_filters"]) == before
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_navigation.py -v`
Expected: FAIL — the detail page does not exist yet.

- [ ] **Step 3: Implement**

`_init_session_state` adds `"page": "screener"` and `"detail_symbol": None`. `render_screener_table` captures the raw symbol list from `page_rows` **before** the `⭐` prefix is applied, calls `st.dataframe(..., on_select="rerun", selection_mode="single-row", key="screener_table")` and on a selected row calls `open_symbol(raw_symbols[selection.selection.rows[0]])` then `st.rerun()`. `render_watchlist_tab` does the same for `watchlist_df` with `key="watchlist_table"`, using `watchlist_df["symbol"]` (no prefix there). `main` branches after `render_pipeline_hud`: when `page == "detail"`, render a `← Back to screener` button calling `close_detail()` + `st.rerun()`, then `render_detail_page(store, detail_symbol)` and `return` before building the tabs. `open_symbol`/`close_detail` only mutate session state.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_navigation.py -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/app.py tests/test_navigation.py
git commit -m "feat(app): open symbol detail page from screener and watchlist rows"
```

---

### Task 11: Full verification and docs

**Files:**
- Modify: `README.md` (one short paragraph under the features list)

- [ ] **Step 1: Live smoke of every parser against NVDA**

```bash
uv run python - <<'PY'
from stonks.detail import load_page
from stonks.detail_parse import parse_forecast, parse_overview, parse_statistics, parse_statement
from stonks.store import SQLiteStore
s = SQLiteStore()
for page in ("overview", "statistics", "forecast"):
    data, at = load_page(s, "NVDA", page, force=True)
    print(page, "ok" if data else "FAILED", at)
print("overview:", parse_overview(load_page(s, "NVDA", "overview", force=True)[0])["market_cap"])
print("sections:", [x["key"] for x in parse_statistics(load_page(s, "NVDA", "statistics", force=True)[0])])
print("targets:", parse_forecast(load_page(s, "NVDA", "forecast", force=True)[0])["targets"])
for period in ("annual", "quarterly"):
    st = parse_statement(load_page(s, "NVDA", "financials", period=period, force=True)[0])
    print(period, len(st["periods"]), "periods", len(st["rows"]), "rows")
PY
```

Expected: every line prints real values, no exceptions.

- [ ] **Step 2: Run the full suite and linters**

```bash
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

Expected: all pass, no formatting diffs. Fix any failure rather than skipping.

- [ ] **Step 3: Manual check in the running app**

Rebuild and confirm the app serves, then in the browser open a symbol from the screener, switch Financials to Quarterly, and use Back:

```bash
docker compose build && docker compose up -d --force-recreate && curl -s -o /dev/null -w "%{http_code}\n" localhost:8502
```

Expected: `200`, and the browser flow works.

- [ ] **Step 4: Note the feature in the README**

Add one paragraph: clicking a symbol (or a watchlist row) opens an in-app detail page with Overview, Financials (annual/quarterly), Statistics, Metrics and Forecast, fetched live from StockAnalysis and cached.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: describe the symbol detail page"
```
