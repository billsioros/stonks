# Yahoo Migration Minor Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the deferred Yahoo migration minors and prove existing screener features still work.

**Architecture:** Tighten query/normalization/derivation in `stonks.yahoo`, remove phantom UI columns from `stonks.config`, and add regression tests across provider, config, presets, and SQLiteStore. No schema, UI, or store filter changes.

**Tech Stack:** Python 3.12, yfinance, Streamlit, SQLite, pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-11-20-yahoo-minors-design.md`

## Global Constraints

- Keep `SQLiteStore.get_stocks` signature unchanged.
- Keep all 9 `POPULAR_SCREENS` applicable without UI edits.
- Missing provider data remains `NULL`; never fabricate values.
- Use `uv run` for all Python commands; ruff is now a dev dependency installed with uv.
- Work only on `feature/yahoo-migration-minors`; do not push or merge.

## Review Focus

- **Multiple enum values must mean union:** `test_build_screener_query_ors_enum_values` asserts one OR operand containing both exchange predicates.
- **Longer annual history must not dilute growth:** `test_cagr_uses_requested_window` asserts a 4-point 10%/yr series yields 10% for `years=3`.
- **Malformed quotes must not poison the universe:** `test_paginate_skips_quotes_without_symbol` asserts no empty row is returned.
- **UI columns must be backed and populated:** `test_config_columns_are_backed_by_store_schema` and `test_enrich_rows_merges_all_derived_values` assert no phantom display columns and all derived values persist.
- **Existing features must still work:** `test_store_filters_sort_search_and_preserves_values` and preset coverage tests assert store behavior and all preset columns remain supported.

---

### Task 1: Enum prefilter OR semantics

**Files:**
- Modify: `src/stonks/yahoo.py`
- Test: `tests/test_yahoo.py`

**Interfaces:**
- Consumes: `build_screener_query(filters: dict[str, dict]) -> EquityQuery`.
- Produces: same signature; multiple values for one enum column become one `or` operand.

- [ ] **Step 1: Write the failing test**

```python
def test_build_screener_query_ors_enum_values():
    query = build_screener_query({"exchange": {"values": ["NYSE", "NASDAQ"]}})
    operands = query.to_dict()["operands"]
    or_operand = next(o for o in operands if o["operator"] == "OR")
    assert {"operator": "EQ", "operands": ["exchange", "NYSE"]} in or_operand["operands"]
    assert {"operator": "EQ", "operands": ["exchange", "NASDAQ"]} in or_operand["operands"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yahoo.py::test_build_screener_query_ors_enum_values -q`
Expected: FAIL, no `OR` operand found.

- [ ] **Step 3: Implement the minimal fix**

In `build_screener_query`, collect enum equalities per column and append one `EquityQuery("or", equalities)` operand.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_yahoo.py::test_build_screener_query_ors_enum_values -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`git add src/stonks/yahoo.py tests/test_yahoo.py && git commit -m "fix: OR enum screener prefilter values"`

---

### Task 2: Growth CAGR uses requested window

**Files:**
- Modify: `src/stonks/yahoo.py`
- Test: `tests/test_yahoo.py`

**Interfaces:**
- Consumes: `_cagr_from_series(series: pd.Series, years: int) -> float | None`.
- Produces: same signature; uses the last `years + 1` points when available.

- [ ] **Step 1: Write the failing test**

```python
def test_cagr_uses_requested_window():
    idx = pd.date_range("2022-01-01", periods=4, freq="YS")
    series = pd.Series([100, 110, 121, 133.1], index=idx)
    assert _cagr_from_series(series, 3) == pytest.approx(10.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yahoo.py::test_cagr_uses_requested_window -q`
Expected: FAIL, result is the 3-year CAGR from the oldest point (~10% is target; current code uses 4-year span).

- [ ] **Step 3: Implement the minimal fix**

In `_cagr_from_series`, set `first = ordered.iloc[-(years + 1)]` when `len(series) > years`; otherwise keep `ordered.iloc[0]`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_yahoo.py::test_cagr_uses_requested_window -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`git add src/stonks/yahoo.py tests/test_yahoo.py && git commit -m "fix: compute CAGR over requested lookback window"`

---

### Task 3: Skip malformed quotes

**Files:**
- Modify: `src/stonks/yahoo.py`
- Test: `tests/test_yahoo.py`

**Interfaces:**
- Consumes: `normalize_quote(raw: dict) -> dict`, `paginate(query, page_size=250, screen_fn=None)`.
- Produces: `normalize_quote` returns `{}` for missing/blank symbol; `paginate` omits empty rows.

- [ ] **Step 1: Write the failing test**

```python
def test_paginate_skips_quotes_without_symbol(monkeypatch):
    def fake_screen(query, offset=None, size=None, **kwargs):
        return {"total": 2, "quotes": [{"marketCap": 1e9}, {"symbol": "AAA", "marketCap": 2e9}]}
    rows = paginate(build_screener_query({}), page_size=250, screen_fn=fake_screen)
    assert [row["symbol"] for row in rows] == ["AAA"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_yahoo.py::test_paginate_skips_quotes_without_symbol -q`
Expected: FAIL, first row has `symbol=None`.

- [ ] **Step 3: Implement the minimal fix**

Return `{}` from `normalize_quote` when `raw.get("symbol")` is missing/blank; in `paginate`, only extend rows with non-empty normalized quotes.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_yahoo.py::test_paginate_skips_quotes_without_symbol -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`git add src/stonks/yahoo.py tests/test_yahoo.py && git commit -m "fix: skip Yahoo quotes without a symbol"`

---

### Task 4: Populate remaining UI columns

**Files:**
- Modify: `src/stonks/yahoo.py`
- Modify: `src/stonks/config.py`
- Modify: `tests/test_yahoo.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: `derive_metrics(info, history, financials, balance_sheet, cashflow)`, `enrich_rows(rows, required_columns, enrich_fn=None)`, `COLUMN_DISPLAY_NAMES`.
- Produces: expanded `_DERIVED_COLUMNS`; `enrich_rows` merges all non-`None` derived values; `COLUMN_DISPLAY_NAMES` contains only schema-backed columns.

- [ ] **Step 1: Write the failing tests**

```python
def test_normalize_quote_maps_quote_type():
    row = normalize_quote({"symbol": "AAA", "quoteType": "EQUITY"})
    assert row["type"] == "EQUITY"
```

```python
def test_derive_metrics_populates_ui_columns():
    info = {
        "industry": "Software",
        "targetMeanPrice": 110.0,
        "currentPrice": 100.0,
        "sharesOutstanding": 1e9,
    }
    idx = pd.date_range("2021-01-01", "2025-01-01", freq="YS")
    financials = pd.DataFrame(
        {"2021": [100, 80], "2022": [110, 88], "2023": [121, 96],
         "2024": [133, 105], "2025": [146, 115]},
        index=["Total Revenue", "Basic EPS"],
    )
    balance_sheet = pd.DataFrame(
        {"2024": [100, 20], "2025": [120, 30]},
        index=["Total Assets", "Long Term Debt"],
    )
    cashflow = pd.DataFrame({"2024": [20], "2025": [25]}, index=["Free Cash Flow"])
    result = derive_metrics(info, None, financials, balance_sheet, cashflow)
    assert result["industry"] == "Software"
    assert result["pt_upside_pct"] == 10.0
    assert result["eps_growth_3y_pct"] == pytest.approx(10.0, abs=0.5)
    assert result["fcf_margin_pct"] == pytest.approx(25 / 146 * 100)
    assert result["free_cash_flow_per_share"] == 25.0
    assert result["revenue_per_share"] == 146.0
    assert result["long_term_debt_to_equity"] == pytest.approx(30 / 120)
    assert result["asset_turnover"] == pytest.approx(146 / 110)
```

```python
def test_enrich_rows_merges_all_derived_values():
    def fake_enrich(symbol):
        return {"symbol": symbol, "industry": "Software", "pt_upside_pct": 10.0}
    rows = enrich_rows([{"symbol": "AAA"}], {"roe_pct"}, enrich_fn=fake_enrich)
    assert rows[0]["industry"] == "Software"
    assert rows[0]["pt_upside_pct"] == 10.0
```

```python
def test_config_columns_are_backed_by_store_schema(tmp_path):
    from stonks.config import COLUMN_DISPLAY_NAMES, NUMERIC_FILTER_COLUMNS, VIEW_PRESETS
    from stonks.store import SQLiteStore
    store = SQLiteStore(tmp_path / "config.db")
    with store._connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(stocks)")}
    assert set(COLUMN_DISPLAY_NAMES) <= columns
    assert {c for cols in VIEW_PRESETS.values() for c in cols} <= set(COLUMN_DISPLAY_NAMES)
    assert set(NUMERIC_FILTER_COLUMNS) <= columns
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_yahoo.py::test_derive_metrics_populates_ui_columns tests/test_yahoo.py::test_enrich_rows_merges_all_derived_values tests/test_config.py -q`
Expected: FAIL for missing keys/values and phantom config columns.

- [ ] **Step 3: Implement the minimal fix**

Map `quoteType` to `type` in `normalize_quote`; extend `_DERIVED_COLUMNS`; derive listed values from Yahoo `info` and annual statements; remove the three phantom display columns from `COLUMN_DISPLAY_NAMES`; change `_enrich_one` to merge all non-`None` derived values without overwriting existing values.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_yahoo.py tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

`git add src/stonks/yahoo.py src/stonks/config.py tests/test_yahoo.py tests/test_config.py && git commit -m "feat: populate remaining UI columns from Yahoo data"`

---

### Task 5: Preset and store regression coverage

**Files:**
- Test: `tests/test_presets.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `POPULAR_SCREENS`, `SCREENER_FIELD_MAP`, `normalize_quote`, `_DERIVED_COLUMNS`, `SQLiteStore`.
- Produces: no production API changes.

- [ ] **Step 1: Write the failing tests**

```python
def test_all_preset_filter_columns_are_supported():
    from stonks.config import NUMERIC_FILTER_COLUMNS
    from stonks.yahoo import SCREENER_FIELD_MAP, _DERIVED_COLUMNS
    supported = (
        set(SCREENER_FIELD_MAP)
        | {"exchange", "currency", "type", "mic"}
        | set(_DERIVED_COLUMNS)
        | set(NUMERIC_FILTER_COLUMNS)
    )
    for preset in POPULAR_SCREENS:
        assert set(preset["filters"]) <= supported
```

```python
def test_store_filters_sort_search_and_preserves_values(store):
    store.save_stock("AAA", {"description": "Alpha", "exchange": "NYSE", "market_cap": 100.0, "pe_ratio": 10.0})
    store.save_stock("BBB", {"description": "Beta", "exchange": "NASDAQ", "market_cap": 50.0, "pe_ratio": 20.0})
    store.save_stock("CCC", {"description": "Null Cap", "exchange": "NYSE", "pe_ratio": 5.0})

    rows, _, total = store.get_stocks(filters={"market_cap": {"min": 60}}, sort_column="pe_ratio", sort_ascending=False)
    assert total == 1
    assert [row["symbol"] for row in rows] == ["AAA"]

    rows, _, total = store.get_stocks(filters={"exchange": {"values": ["NASDAQ"]}})
    assert total == 1
    assert [row["symbol"] for row in rows] == ["BBB"]

    rows, _, total = store.get_stocks(search_query="Alpha")
    assert total == 1
    assert rows[0]["symbol"] == "AAA"

    rows, total_pages, total = store.get_stocks(page=2, page_size=1, sort_column="symbol")
    assert total == 3 and total_pages == 3
    assert rows[0]["symbol"] == "BBB"

    store.save_stock("AAA", {"pe_ratio": None, "market_cap": 120.0})
    row = store.get_stocks(search_query="Alpha")[0][0]
    assert row["pe_ratio"] == 10.0
    assert row["market_cap"] == 120.0
```

- [ ] **Step 2: Run the characterization tests**

Run: `uv run pytest tests/test_presets.py tests/test_store.py -q`
Expected: PASS; these tests lock in existing behavior and require no production change.

- [ ] **Step 3: Run full suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 4: Commit**

`git add tests/test_presets.py tests/test_store.py && git commit -m "test: cover presets and existing store features"`

---

### Task 6: Full verification

**Files:**
- No source changes expected.

- [ ] **Step 1: Full suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 2: Lint**

Run: `uv run ruff check src tests`
Expected: `All checks passed!`

- [ ] **Step 3: App import**

Run: `uv run python -c "from stonks.app import app; print('app import ok')"`
Expected: prints `app import ok`.

- [ ] **Step 4: Branch hygiene**

Run: `git status --short && git branch --show-current`
Expected: clean tree on `feature/yahoo-migration-minors`; no push or merge performed.
