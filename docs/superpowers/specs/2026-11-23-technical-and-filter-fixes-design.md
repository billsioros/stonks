# Screener Architecture, Technical Robustness & Investment Logic Design

## Overview

This document specifies a comprehensive upgrade to the stock screener application, resolving:
1. **19 Verified Technical & Correctness Issues** (SQL safety, filter validation, UI rendering bugs, and worker sync resilience).
2. **Core Investment Logic Flaws** (peak-earnings cyclicality traps, backward-looking growth extrapolation, automated valuation model outliers, and balance sheet/cash quality guardrails).
3. **Reference Site Consistency & Non-Destructive Metric Retention**:
   - All original metrics (`shares_insiders_pct`, `dcf_fair_value`, `dcf_upside_pct`, `lynch_fair_value`, `lynch_upside_pct`, `hedge_fund_buys`) remain **untouched in their original columns**.
   - Fixed, normalized, and composite metrics are added in **new dedicated columns alongside the originals**, preserving complete data continuity and guaranteeing that external sanity checks (StockAnalysis, HedgeFollow, GuruFocus) experience zero divergence.

---

## Part 1: Schema Architecture & Side-by-Side Metrics

### 1.1 Non-Destructive Column Pairings in SQLite (`stocks` table)
To avoid mutating existing data or breaking reference site checks, all improvements are introduced in dedicated new columns alongside the originals:

| Original Column (Kept Intact) | New Fixed / Enhanced Column | Description & Units |
| :--- | :--- | :--- |
| `shares_insiders_pct REAL` (Fraction: `0.05` = 5%) | `shares_insiders_percent REAL` | True percentage (`5.0` = 5%), directly reflecting StockAnalysis API without division by 100. |
| `ev_to_ebitda REAL`, `roic_5y_avg_pct REAL` | `cyclical_peak_risk INTEGER` | `1` when stock is in a cyclical industry with low multiple (< 8x) and peak returns; `0` otherwise. |
| `dcf_upside_pct REAL`, `lynch_upside_pct REAL` | `valuation_triangulation TEXT` | Composite classification: `"Strong Consensus"`, `"Moderate Value"`, `"Model Divergence / Outlier"`, `"Cyclical Distorted"`, `"Unrated"`. |
| `dcf_upside_pct REAL`, `lynch_upside_pct REAL` | `valuation_upside_capped_pct REAL` | Display-capped upside (max `150.0%`) to prevent extreme multi-year cyclical outliers from distorting rankings. |
| `hedge_fund_buys INTEGER` (`0` or `1`) | *(Contextualized in UI/prompts)* | Unmutated binary flag in DB; labeled as **"13F Whale"** with tooltips on 45-day lag and institutional crowding. |

### 1.2 Schema Migration (`src/stonks/store.py`)
In `_migrate_schema(conn)`:
```python
stock_columns = {row[1] for row in conn.execute("PRAGMA table_info(stocks)")}
new_columns = [
    ("shares_insiders_percent", "REAL"),
    ("cyclical_peak_risk", "INTEGER"),
    ("valuation_triangulation", "TEXT"),
    ("valuation_upside_capped_pct", "REAL"),
]
for column_name, column_type in new_columns:
    if column_name not in stock_columns:
        conn.execute(f"ALTER TABLE stocks ADD COLUMN {column_name} {column_type}")
```
* **Backfill for Existing Databases**:
  On startup, if `shares_insiders_percent` is `NULL` but `shares_insiders_pct` is present, populate it via:
  ```sql
  UPDATE stocks
  SET shares_insiders_percent = shares_insiders_pct * 100.0
  WHERE shares_insiders_percent IS NULL AND shares_insiders_pct IS NOT NULL;
  ```

### 1.3 Provider Ingestion (`src/stonks/stockanalysis.py`, `src/stonks/valuation.py`)
* In `DATA_POINT_MAP`:
  - `"shares_insiders_pct": ("sharesInsiders", _fraction)` (preserved for reference screen checks).
  - `"shares_insiders_percent": ("sharesInsiders", _identity)` (new direct percentage mapping).
* In row building:
  - Compute `cyclical_peak_risk`, `valuation_triangulation`, and `valuation_upside_capped_pct` per stock during snapshot build.

---

## Part 2: Technical & SQL Robustness

### 2.1 Filter Validation Engine & Safe Queries (`src/stonks/store.py`)
* **Unknown Columns**: When iterating `filters.items()`, if `col` is not in `numeric_columns` and not in `enum_columns`, append a warning: `f"Ignored unknown filter column: '{col}'"`. Do not generate a `WHERE` clause for it.
* **Empty Enum Values**: If `col in enum_columns` and `"values"` is in `spec`:
  - If `spec["values"] == []`: immediately match 0 rows (append `1 = 0` to where clauses) so filtering by an empty set returns 0 rows instead of all stocks.
* **Inverted Bounds (`min > max`)**: If `spec.get("min") is not None and spec.get("max") is not None`:
  - Coerce both via `float()`. If `min_val > max_val`, append a warning: `f"Filter '{col}' has min ({min_val}) > max ({max_val}); matches 0 rows"`. Append `1 = 0` to where clauses.
* **Numeric Sanitization**: For all numeric filter inputs, coerce with `float()` and verify `math.isfinite()`. Skip non-finite values (`NaN`, `Infinity`) and log a warning.
* **Backwards-Compatible Diagnostics (`StockQueryResult`)**:
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
* **Atomic Queries & Safe Pagination**:
  - Run `COUNT(*)` and `SELECT` within a single `with self._connect() as conn:` connection context block.
  - Bound `page_size = max(1, min(int(page_size), 100_000))`.
  - Calculate `total_pages = max(1, (total_matching + page_size - 1) // page_size)`.
  - Calculate `safe_page = max(1, min(int(page), total_pages))`.
  - Calculate `offset = (safe_page - 1) * page_size`.
  - Append `LIMIT ? OFFSET ?` with `params.extend([page_size, offset])` instead of f-string interpolation.
* **SQL Injection & Schema Guard**:
  - Maintain the strict column whitelist for `sort_column`.
  - Add an automated unit test verifying that `set(numeric_columns | enum_columns) <= set(table_columns)` from `PRAGMA table_info(stocks)`.

### 2.2 UI/UX Logic (`src/stonks/app.py`)
* **Active Filter HTML Formatting Fix**:
  Use `html.escape` and regex substitution to prevent unclosed `<strong>` tags:
  ```python
  import html, re

  html_parts = []
  for p in filter_parts:
      safe_p = html.escape(p)
      formatted = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe_p)
      html_parts.append(formatted)
  ```
* **Filter Pruning Helper**:
  Add `_prune_filters(filters: dict[str, Any]) -> dict[str, Any]` to remove empty `{}` and `{min: None, max: None}` dicts. Apply before updating session state on "Apply" and when saving screens.
* **Unified Screen State Loading**:
  Implement `apply_screen_state(screen: dict[str, Any]) -> None` with consistent `sort_ascending = screen.get("sort_ascending", True)` default.
* **Diagnostics & Sync Warning Display**:
  - Render `result.warnings` via `st.warning`.
  - If `last_sync_status == "failed"` or sync is overdue, display an alert banner above the screener table.

### 2.3 Background Worker Resilience & Sanity Checks (`src/stonks/worker.py`, `src/stonks/sanity.py`)
* **Sync Status Persistence**:
  In `worker.job()`, save `last_sync_status`, `last_sync_time`, `last_successful_sync_at`, and `last_sync_error` to database metadata.
* **Metric Drift Spot-Checks**:
  In `sanity.check_stockanalysis`, spot-check up to 10 overlapping stocks across `free_cash_flow`, `net_income`, `ev_to_ebitda`, `shares_insiders_pct`, and `gross_margin_pct`. Assert relative deviation within 2%.
* **Sanity Tolerance Wording & Size Assertions**:
  Update description to "Within tolerance (10% drift)"; assert `total < 100_000` to prevent silent page truncation.
* **Alert Baseline & Empty Watchlist Guards**:
  Verify and unit-test `_watched_rows(store, set()) == {}` and `evaluate_alerts(None, row) == []`.

---

## Part 3: Screener Investment Logic & Valuation Guardrails

### 3.1 Peak-Earnings & Cyclicality Detection
* **Cyclical Industry Definition** (in `src/stonks/config.py`):
  ```python
  CYCLICAL_INDUSTRIES = {
      "Metals & Mining",
      "Gold",
      "Silver",
      "Agricultural Inputs",
      "Chemicals",
      "Semiconductors",
      "Semiconductor Equipment & Materials",
      "Engineering & Construction",
      "Oil & Gas E&P",
      "Oil & Gas Refining & Marketing",
      "Steel",
      "Building Products & Equipment",
  }
  ```
* **Cyclical Peak Risk Heuristic**:
  `cyclical_peak_risk = 1` when:
  - `industry in CYCLICAL_INDUSTRIES`
  - `ev_to_ebitda is not None and ev_to_ebitda < 8.0`
  - `(roic_5y_avg_pct is not None and roic_5y_avg_pct > 20.0)` or `(fcf_growth_5y_pct is not None and fcf_growth_5y_pct > 25.0)`
  Otherwise `0`.
* **UI Visual Warning & Tooltip**:
  In screener table, render ⚠️ badge on flagged names:
  *"⚠️ Cyclical Peak Risk: Low EV/EBITDA multiple combined with peak trailing returns in a cyclical industry. Denominated EBITDA may be temporarily inflated."*

### 3.2 Valuation Triangulation & Outlier Capping
* **Triangulation Helper (`src/stonks/valuation.py`)**:
  `evaluate_valuation_triangulation(dcf_upside, lynch_upside, pt_upside, peg_ratio, cyclical_risk)`:
  - Signal counts:
    - `dcf_upside > 15.0`
    - `lynch_upside > 15.0`
    - `pt_upside > 15.0`
    - `0 < peg_ratio <= 1.5`
  - Classification:
    - `"Strong Consensus"`: >= 3 signals agree AND `cyclical_risk == 0`.
    - `"Moderate Value"`: Exactly 2 signals agree.
    - `"Model Divergence / Outlier"`: Single model upside > 150% while other models are missing, negative, or PEG > 2.0.
    - `"Cyclical Distorted"`: High upside on stock flagged with `cyclical_peak_risk == 1`.
    - `"Unrated / Insufficient Data"`: Fewer than 2 models available.
* **Capped Display Upside**:
  `valuation_upside_capped_pct`: min(average of available upsides, 150.0). Keeps sorting and charts meaningful.

### 3.3 Presets Strategy: Reference Screen Untouched + New Disciplined Preset
* **Untouched Reference Preset**:
  `"💎 The Quality Screen"` retains its exact original 14 filters (including `shares_insiders_pct: {"min": 0.000001}`), guaranteeing that `default_screen()` and `check_stockanalysis` (36 symbols) pass without drift.
* **New Enhanced Preset: `"🛡️ Disciplined Quality Compounders"`**:
  - `fcf_margin_pct`: `{"min": 5.0}` (eliminates paper earnings).
  - `current_ratio`: `{"min": 1.0}` (eliminates liquidity stress).
  - `short_pct`: `{"max": 10.0}` (avoids collapse bets).
  - `debt_to_equity`: `{"max": 1.0}` (prudent leverage).
  - `shares_insiders_percent`: `{"min": 0.01}` (> 0% insider ownership on the true percentage scale).
  - `cyclical_peak_risk`: `{"max": 0}` (filters out peak cyclical traps).
  - `sort_column`: `"ev_to_ebitda"`, `sort_ascending`: `True`.

### 3.4 13F Whale Indicator Contextualization
* UI header labeled **"13F Whale"** with tooltip explaining 45-day lag and institutional crowding; treating `0` as neutral.
* Report prompts in `report.py` instruct AI not to penalize `hedge_fund_buys == 0`.

---

## Part 4: Verification, Testing & External Benchmarks

1. **External Benchmarks Preservation**:
   - `check_stockanalysis`: Tests `default_screen()` against live StockAnalysis data; passes with 0 drift.
   - `check_gurufocus_models`: Tests that `dcf_fair_value`, `lynch_fair_value`, and upsides match formulas; unmutated DB columns guarantee 100% agreement.
   - `check_hedgefollow`: Tests `hedge_fund_buys` overlap; binary column preservation guarantees >= 80% match.
2. **Unit & Integration Tests**:
   - `tests/test_store.py`: Filter validation, empty enum list, min > max, safe LIMIT/OFFSET, schema PRAGMA assertion.
   - `tests/test_stockanalysis.py`: Both `shares_insiders_pct` and `shares_insiders_percent` populated accurately.
   - `tests/test_valuation.py`: `cyclical_peak_risk`, `evaluate_valuation_triangulation`, capped upside calculations.
   - `tests/test_worker.py` & `tests/test_sanity.py`: Sync metadata persistence, metric drift detection.
   - `tests/test_screener_ui.py`: HTML formatting closed tags, filter pruning, unified screen loading.
