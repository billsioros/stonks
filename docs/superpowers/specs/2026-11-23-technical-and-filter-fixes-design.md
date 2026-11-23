# Screener Architecture, Technical Robustness & Investment Logic Design

## Overview

This document specifies a comprehensive upgrade to the stock screener application, resolving:
1. **19 Verified Technical & Correctness Issues** (SQL safety, unit consistency, filter validation, UI rendering bugs, and worker sync resilience).
2. **Core Investment Logic Flaws** (peak-earnings cyclicality traps, backward-looking growth extrapolation, automated valuation model outliers, and balance sheet/cash quality guardrails).
3. **Reference Site Consistency** (preserving strict alignment with StockAnalysis, HedgeFollow, and GuruFocus DCF/Peter Lynch benchmarks).

---

## Part 1: Technical & SQL Robustness, Unit Consistency & Data Correctness

### 1.1 `shares_insiders_pct` Standardization & Startup Migration
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

### 1.2 Filter Validation Engine & Safe Queries (`src/stonks/store.py`)
* **Unknown Columns**: When iterating `filters.items()`, if `col` is not in `numeric_columns` and not in `enum_columns`, append a warning: `f"Ignored unknown filter column: '{col}'"`. Do not generate a `WHERE` clause for it.
* **Empty Enum Values**: If `col in enum_columns` and `"values"` is in `spec`:
  - If `spec["values"] == []`: immediately short-circuit to match 0 rows (append `1 = 0` to where clauses) so filtering by an empty set returns 0 rows instead of all stocks.
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
* **Atomic Queries & Safe Bound Parameterization**:
  - Run `COUNT(*)` and `SELECT` within a single `with self._connect() as conn:` connection context block.
  - Bound `page_size = max(1, min(int(page_size), 100_000))`.
  - Calculate `total_pages = max(1, (total_matching + page_size - 1) // page_size)`.
  - Calculate `safe_page = max(1, min(int(page), total_pages))`.
  - Calculate `offset = (safe_page - 1) * page_size`.
  - Append `LIMIT ? OFFSET ?` with `params.extend([page_size, offset])` instead of f-string interpolation.
* **SQL Injection & Schema Guard**:
  - Maintain the strict column whitelist for `sort_column`.
  - Add an automated unit test verifying that `set(numeric_columns | enum_columns) <= set(table_columns)` from `PRAGMA table_info(stocks)`.

### 1.3 UI/UX Logic (`src/stonks/app.py`)
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

### 1.4 Background Worker Resilience & Sanity Checks (`src/stonks/worker.py`, `src/stonks/sanity.py`)
* **Sync Status Persistence**:
  In `worker.job()`, save `last_sync_status`, `last_sync_time`, `last_successful_sync_at`, and `last_sync_error` to database metadata.
* **Metric Drift Spot-Checks**:
  In `sanity.check_stockanalysis`, spot-check up to 10 overlapping stocks across `free_cash_flow`, `net_income`, `ev_to_ebitda`, `shares_insiders_pct`, and `gross_margin_pct`. Assert relative deviation within 2%.
* **Sanity Tolerance Wording & Size Assertions**:
  Update description to "Within tolerance (10% drift)"; assert `total < 100_000` to prevent silent page truncation.
* **Alert Baseline & Empty Watchlist Guards**:
  Verify and unit-test `_watched_rows(store, set()) == {}` and `evaluate_alerts(None, row) == []`.

---

## Part 2: Screener Investment Logic & Valuation Guardrails

### 2.1 Peak-Earnings & Cyclicality Detection
* **The Problem**: Sorting by `ev_to_ebitda` ascending prioritizes cyclical companies at peak operational cycles (e.g., gold miners like `DRD`, fertilizers like `CF`, memory semiconductors like `MU`, construction like `IESC`), where EBITDA is temporarily inflated, masquerading as durable deep-value compounders.
* **Specification**:
  1. **Cyclical Industry Definition** (in `src/stonks/config.py`):
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
  2. **Cyclical Peak Risk Heuristic**:
     A stock is flagged as `cyclical_peak_risk = True` when:
     - `industry in CYCLICAL_INDUSTRIES`
     - `ev_to_ebitda is not None and ev_to_ebitda < 8.0`
     - `(roic_5y_avg_pct is not None and roic_5y_avg_pct > 20.0)` or `(fcf_growth_5y_pct is not None and fcf_growth_5y_pct > 25.0)`
  3. **UI Visual Warning & Tooltip**:
     - In the screener table and detail page, render a ⚠️ badge next to the ticker or multiple:
       *"⚠️ Cyclical Peak Risk: Low EV/EBITDA multiple combined with peak trailing returns in a cyclical industry.Denominated EBITDA may be temporarily inflated."*
  4. **Filterable Cyclicality Flag**:
     - Add an opt-in screener filter or toggle: *"Exclude potential cyclical peaks"* or allow filtering `cyclical_risk = False`.

### 2.2 Valuation Triangulation & Outlier Capping
* **The Problem**: Automated DCF and Peter Lynch formulas mechanically extrapolate peak trailing EPS (e.g. `MU` at +212% Lynch upside, `DRD` at +338% DCF upside). Moreover, missing DCF values (`null`) leave holes in rankings.
* **Specification**:
  1. **Triangulation Helper (`src/stonks/valuation.py`)**:
     Implement `evaluate_valuation_triangulation(dcf_upside, lynch_upside, pt_upside, peg_ratio, cyclical_risk)`:
     - **Triangulation Agreement Score**: Counts how many independent valuation signals indicate positive value:
       - Signal 1: `dcf_upside is not None and dcf_upside > 15.0`
       - Signal 2: `lynch_upside is not None and lynch_upside > 15.0`
       - Signal 3: `pt_upside is not None and pt_upside > 15.0` (Analyst Consensus)
       - Signal 4: `peg_ratio is not None and 0 < peg_ratio <= 1.5`
     - **Classification**:
       - `"Strong Consensus"`: At least 3 signals agree AND `cyclical_risk is False`.
       - `"Moderate Value"`: Exactly 2 signals agree.
       - `"Model Divergence / Outlier"`: Single model upside > 150% while other models are missing, negative, or PEG > 2.0.
       - `"Cyclical Distorted"`: High upside on cyclical stock flagged with cyclical peak risk.
       - `"Unrated / Insufficient Data"`: Fewer than 2 models available.
  2. **Outlier Display Capping**:
     - When displaying upside in the UI, values exceeding `+150%` are annotated: `+150%+ (Outlier)` or capped visually so an astronomical 500% extrapolation does not distort sorting or charts.
  3. **Handling Missing Valuation Models**:
     - In AI symbol reports and detail view, explicitly note when DCF is `null` (e.g., negative trailing cash flows or incomplete analyst long-term forecasts) rather than treating it as 0% upside.

### 2.3 Balance-Sheet & Cash-Quality Guardrails in Screener Presets
* **The Problem**: `"💎 The Quality Screen"` preset required positive cash flow (`$1M`), but allowed paper-thin margins, extreme short interest, and weak liquidity to slip through.
* **Specification**:
  Update `"💎 The Quality Screen"` in `src/stonks/presets.py` to include:
  - `fcf_margin_pct`: `{"min": 5.0}` (requires real cash conversion per dollar of revenue).
  - `current_ratio`: `{"min": 1.0}` (protects against immediate working-capital stress).
  - `short_pct`: `{"max": 10.0}` (filters out extreme short interest / fraud suspicion).
  - `shares_insiders_pct`: `{"min": 0.0001}` (enforces non-zero insider ownership on the normalized percentage scale).
  - `debt_to_equity`: `{"max": 1.0}` (retains leverage discipline).

### 2.4 13F Whale Indicator Contextualization
* **The Problem**: Binary `hedge_fund_buys` (`0` vs `1`) is backward-looking (up to 45 days after quarter-end) and creates a false negative on small-cap or specialized compounders not tracked by 13F whale aggregators.
* **Specification**:
  1. **UI Header & Tooltip**:
     - Display column header as **"13F Whale"** with tooltip:
       *"Quarterly 13F filing top buy (HedgeFollow). Subject to 45-day lag and institutional crowding. Treat 0 as neutral/untracked, not negative."*
  2. **AI Decision Report Prompt Guidance**:
     - In `src/stonks/report.py`, update prompt instructions to clarify that `hedge_fund_buys == 0` is neutral and that 13F filings reflect lagging sentiment.

---

## Part 3: Architecture & Data Flow

```
+-------------------------------------------------------------+
| StockAnalysis API / HedgeFollow / Treasury Yield Endpoints  |
+-------------------------------------------------------------+
                              |
                     fetch_rows / apply_flags
                              v
+-------------------------------------------------------------+
| Data Harmonization & Valuation Engine                       |
| - shares_insiders_pct normalized to percentage (5.0 = 5%)   |
| - dcf_fair_value & lynch_fair_value computed (GuruFocus)     |
| - cyclical_peak_risk & valuation_triangulation computed     |
+-------------------------------------------------------------+
                              |
                        replace_stocks
                              v
+-------------------------------------------------------------+
| SQLite Store (Atomic Single-Connection Queries)             |
| - Validates columns, handles min > max, sanitizes floats    |
| - Safe LIMIT ? OFFSET ? pagination                          |
| - Returns StockQueryResult(rows, total_pages, count, warns) |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
| Streamlit Screener UI & Reports                             |
| - Active filters HTML safe escaped & regex formatted        |
| - Pruned filter dicts; unified apply_screen_state           |
| - Cyclical peak badges & valuation triangulation display    |
| - Sync staleness / error banner above table                 |
+-------------------------------------------------------------+
```

---

## Part 4: Verification & Testing Plan

1. **Store & Filter Testing (`tests/test_store.py`)**:
   - Unknown column warning generation and graceful execution.
   - Empty enum list `values: []` returns 0 rows.
   - Inverted bounds `min > max` generates warning and returns 0 rows.
   - Parameterized `LIMIT ? OFFSET ?` and safe `page_size <= 0` handling.
   - Schema consistency test asserting all query/sort columns exist in the SQLite `stocks` table.
2. **Unit & Migration Testing (`tests/test_stockanalysis.py`, `tests/test_presets.py`)**:
   - `shares_insiders_pct` stored as percentage (`5.0` for 5%).
   - `The Quality Screen` preset uses normalized percentage bounds and new guardrails (`fcf_margin_pct >= 5.0`, `current_ratio >= 1.0`, `short_pct <= 10.0`).
   - SQLite database startup migration converts fractional insider shares to percentage scale.
3. **Investment Logic & Valuation Testing (`tests/test_valuation.py`, `tests/test_config.py`)**:
   - `cyclical_peak_risk` flag correctly detects cyclical industries at low EV/EBITDA and high ROIC.
   - `evaluate_valuation_triangulation` correctly classifies Strong Consensus, Model Divergence / Outlier, and Cyclical Distorted.
   - Outlier upside display formatting.
4. **Worker & Sanity Testing (`tests/test_worker.py`, `tests/test_sanity.py`)**:
   - Worker persists sync failure and success metadata.
   - Sanity check detects metric value drift when key numeric columns are perturbed.
   - Empty watchlist and `previous=None` alert evaluation tests.
   - Existing sanity checks for HedgeFollow, StockAnalysis, and GuruFocus models continue to pass without divergence.
5. **UI Testing (`tests/test_screener_ui.py` or existing UI suites)**:
   - Active filters HTML formatting properly closes `<strong>...</strong>` tags with HTML escaping.
   - `_prune_filters` removes empty `{}` and `{min: None, max: None}` dicts.
   - `apply_screen_state` sets consistent defaults.
