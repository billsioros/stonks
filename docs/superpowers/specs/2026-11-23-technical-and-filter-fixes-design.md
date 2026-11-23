# Technical Robustness, Filter Correctness & Unit Consistency Design (Phase 1)

## Overview

This document specifies the technical and data-correctness hardening of the stock screener application (Phase 1). It addresses 19 verified issues spanning filter correctness, unit consistency, SQL query robustness, UI/UX logic, and background worker resilience, while strictly preserving alignment with external data sources (StockAnalysis, HedgeFollow, and GuruFocus DCF/Peter Lynch valuation models).

---

## 1. Unit & Data Correctness

### 1.1 `shares_insiders_pct` Standardization
* **Problem**: In `src/stonks/stockanalysis.py`, `sharesInsiders` from StockAnalysis was transformed using `_fraction` (`value / 100`), storing values like `0.05` for 5%. All other `*_pct` columns (`gross_margin_pct`, `roic_5y_avg_pct`, `short_pct`, etc.) use `_identity`, storing `5.0` for 5%. In presets and UI filters, this inconsistency created major confusion (e.g. `"shares_insiders_pct": {"min": 0.000001}`).
* **Specification**:
  1. **Provider Mapping**: Update `DATA_POINT_MAP` in `src/stonks/stockanalysis.py` to map `"shares_insiders_pct"` with `_identity` instead of `_fraction`.
  2. **Preset Definition**: Update `💎 The Quality Screen` in `src/stonks/presets.py` to set `"shares_insiders_pct": {"min": 0.0001}` (enforcing non-zero insider ownership on the percentage scale).
  3. **Database Migration**: In `src/stonks/store.py`, add a one-time migration in `_migrate_schema(conn)`:
     - Check if `metadata` key `migration_shares_insiders_pct_v1` is `"done"`.
     - If not done:
       ```sql
       UPDATE stocks
       SET shares_insiders_pct = shares_insiders_pct * 100.0
       WHERE shares_insiders_pct IS NOT NULL
         AND shares_insiders_pct > 0
         AND shares_insiders_pct < 1.0;
       ```
     - Set `migration_shares_insiders_pct_v1` to `"done"`.

---

## 2. Filter & SQL Safety (`src/stonks/store.py`)

### 2.1 Filter Validation Engine
* **Unknown Columns**: When iterating `filters.items()`, if `col` is not in `numeric_columns` and not in `enum_columns`, append a warning: `f"Ignored unknown filter column: '{col}'"`. Do not generate a `WHERE` clause for it.
* **Empty Enum Values**: If `col in enum_columns` and `"values"` is in `spec`:
  - If `spec["values"] == []`: immediately short-circuit to match 0 rows (append `1 = 0` to where clauses) so filtering by an empty set returns 0 rows instead of all stocks.
* **Inverted Bounds (`min > max`)**: If `spec.get("min") is not None and spec.get("max") is not None`:
  - Coerce both via `float()`. If `min_val > max_val`, append a warning: `f"Filter '{col}' has min ({min_val}) > max ({max_val}); matches 0 rows"`. Append `1 = 0` to where clauses.
* **Numeric Sanitization**: For all numeric filter inputs, coerce with `float()` and verify `math.isfinite()`. Skip non-finite values (`NaN`, `Infinity`) and log a warning.

### 2.2 Backwards-Compatible Query Diagnostics (`StockQueryResult`)
* To communicate validation warnings to callers without breaking existing callers unpacking `rows, total_pages, total_matching = store.get_stocks(...)`:
  ```python
  class StockQueryResult(tuple):
      """3-tuple of (rows, total_pages, total_matching) with diagnostic warnings."""
      def __new__(
          cls,
          rows: list[dict[str, Any]],
          total_pages: int,
          total_matching: int,
          warnings: list[str] | None = None,
      ):
          instance = super().__new__(cls, (rows, total_pages, total_matching))
          instance.rows = rows
          instance.total_pages = total_pages
          instance.total_matching = total_matching
          instance.warnings = warnings or []
          return instance
  ```

### 2.3 Atomic Queries & Safe Pagination
* **Single Read Transaction**: Run `COUNT(*)` and `SELECT` within a single `with self._connect() as conn:` connection context block.
* **Safe Bound Parameterization**:
  - Bound `page_size = max(1, min(int(page_size), 100_000))`.
  - Calculate `total_pages = max(1, (total_matching + page_size - 1) // page_size)`.
  - Calculate `safe_page = max(1, min(int(page), total_pages))`.
  - Calculate `offset = (safe_page - 1) * page_size`.
  - Append `LIMIT ? OFFSET ?` with `params.extend([page_size, offset])` instead of f-string interpolation.

### 2.4 SQL Injection & Schema Guard
* Maintain the strict column whitelist for `sort_column`.
* Add an automated unit test verifying that `set(numeric_columns | enum_columns) <= set(table_columns)` from `PRAGMA table_info(stocks)`.

---

## 3. UI/UX Logic (`src/stonks/app.py`)

### 3.1 Active Filter HTML Formatting Fix
* **Problem**: Chained `str.replace("**", "<strong>").replace("**", "</strong>")` replaces all occurrences with opening tags, breaking summary layout.
* **Fix**: Use `html.escape` and regex substitution:
  ```python
  import html, re

  html_parts = []
  for p in filter_parts:
      safe_p = html.escape(p)
      formatted = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe_p)
      html_parts.append(formatted)
  ```

### 3.2 Filter Pruning Helper
* Add `_prune_filters(filters: dict[str, Any]) -> dict[str, Any]`:
  - Retains numeric filters only if at least one of `min` or `max` is not `None`.
  - Retains enum filters only if `values` is non-empty.
* Apply pruning before updating `st.session_state["active_filters"]` on form submission ("Apply"), and before saving screens to the database.

### 3.3 Unified Screen State Loading
* Replace divergent preset loading and saved-screen loading blocks with a single helper:
  ```python
  def apply_screen_state(screen: dict[str, Any]) -> None:
      st.session_state["active_filters"] = _prune_filters(screen.get("filters", {}))
      st.session_state["view_preset"] = screen.get("view_preset", "Overview")
      st.session_state["sort_column"] = screen.get("sort_column")
      st.session_state["sort_ascending"] = screen.get("sort_ascending", True)
      st.session_state["current_page"] = 1
      st.session_state["search_query"] = screen.get("search_query", "")
  ```

### 3.4 Diagnostics & Sync Warning Display
* If `result.warnings` contains warnings, display them via `st.warning`.
* If `last_sync_status == "failed"` or sync is overdue, display an alert banner above the screener table.

---

## 4. Worker Resilience & Sanity Checks (`src/stonks/worker.py`, `src/stonks/sanity.py`)

### 4.1 Sync Status Persistence
* In `worker.job()`:
  - On success:
    - `store.save_metadata("last_sync_status", "success")`
    - `store.save_metadata("last_sync_time", str(time.time()))`
    - `store.save_metadata("last_successful_sync_at", str(time.time()))`
    - `store.save_metadata("last_sync_error", "")`
  - On exception or empty payload:
    - `store.save_metadata("last_sync_status", "failed")`
    - `store.save_metadata("last_sync_time", str(time.time()))`
    - `store.save_metadata("last_sync_error", str(exc))`

### 4.2 Metric Value Drift Spot-Checks in `sanity.py`
* In `check_stockanalysis`:
  - Sample up to 10 overlapping stocks between `stored` and `fresh`.
  - Compare key numeric metrics: `free_cash_flow`, `net_income`, `ev_to_ebitda`, `shares_insiders_pct`, and `gross_margin_pct`.
  - Assert relative deviation is within 2% (`math.isclose(a, b, rel_tol=0.02)`).
  - If any metric diverges beyond tolerance, mark check `ok=False` and report the specific metric, ticker, and values in `detail`.
* Update sanity wording to indicate "Within tolerance (10% drift)" instead of "exact match".
* Add `assert total < 100_000` on the sanity scratch DB query to guarantee silent truncation cannot occur.

### 4.3 Alert Baseline & Empty Watchlist Guards
* Verify and add unit tests for:
  - `_watched_rows(store, set()) == {}`
  - `evaluate_alerts(None, row) == []`

---

## 5. Verification & Testing Plan

1. **Unit Tests**:
   - `tests/test_store.py`:
     - Test unknown column warning generation and graceful query execution.
     - Test empty enum list `values: []` returns 0 rows.
     - Test inverted bounds `min > max` generates warning and returns 0 rows.
     - Test non-finite numeric bounds skipped with warning.
     - Test parameterized `LIMIT ? OFFSET ?` and safe `page_size <= 0` handling.
     - Test schema consistency asserting all query/sort columns exist in the SQLite `stocks` table.
   - `tests/test_stockanalysis.py` & `tests/test_presets.py`:
     - Test `shares_insiders_pct` stored as percentage (`5.0` for 5%).
     - Test `The Quality Screen` preset uses normalized percentage bounds.
     - Test SQLite database migration converts fractional insider shares to percentage scale.
   - `tests/test_worker.py` & `tests/test_sanity.py`:
     - Test worker persists sync failure and success metadata.
     - Test sanity check reports failure when key numeric metrics drift.
     - Test empty watchlist and `previous=None` alert evaluation.
   - `tests/test_screener_ui.py` (or UI tests):
     - Test active filters HTML formatting closes `<strong>` tags properly without raw string leaks.
     - Test `_prune_filters` removes empty `{}` and `{min: None, max: None}` dicts.
     - Test `apply_screen_state` applies consistent defaults.
2. **Regression Check**:
   - Run the complete test suite with `.venv/bin/pytest`.
   - Verify existing sanity checks for HedgeFollow, StockAnalysis, and GuruFocus models continue to pass without divergence.
