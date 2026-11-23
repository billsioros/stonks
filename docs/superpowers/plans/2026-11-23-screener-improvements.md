# Screener Robustness, Filter Correctness & Investment Logic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the stock screener application against SQL/filter bugs, standardize units, introduce side-by-side cyclical peak risk and valuation triangulation metrics, and ensure background worker sync resilience without drifting from external reference benchmarks (StockAnalysis, GuruFocus, HedgeFollow).

**Architecture:** Maintain original database columns unmutated to preserve external benchmark checks (`check_stockanalysis`, `check_gurufocus_models`, `check_hedgefollow`) while adding new normalized percentage and composite classification columns side-by-side (`shares_insiders_percent`, `cyclical_peak_risk`, `valuation_triangulation`, `valuation_upside_capped_pct`). Query execution is made atomic with single-connection reads, parameterized pagination, and backwards-compatible `StockQueryResult` diagnostics. UI fixes resolve HTML tag parsing bugs, filter pruning, and surface real-time sync staleness.

**Tech Stack:** Python 3.12, SQLite 3, Streamlit, Pytest, Pandas, Regex.

## Global Constraints

- **Python Version & Tooling**: Python 3.12 running under `.venv/bin/pytest`.
- **Database**: SQLite 3 with atomic transactions via `store._connect()`.
- **No In-Place Mutation of Benchmark Columns**: `shares_insiders_pct`, `dcf_fair_value`, `dcf_upside_pct`, `lynch_fair_value`, `lynch_upside_pct`, and `hedge_fund_buys` must remain in their original formats in SQLite.
- **Reference Benchmark Integrity**: `sanity.check_stockanalysis`, `sanity.check_gurufocus_models`, and `sanity.check_hedgefollow` must pass with zero divergence.
- **Backwards Compatibility**: `store.get_stocks(...)` must return an object that safely unpacks as `(rows, total_pages, total_matching)` for all existing callers while exposing `.warnings`.

---

### Task 1: Database Schema Expansion & Column Migration

**Files:**
- Modify: `src/stonks/store.py:10-77, 210-245`
- Modify: `src/stonks/config.py:20-80, 100-165`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `PRAGMA table_info(stocks)`
- Produces: `NEW_COLUMNS = ("shares_insiders_percent", "cyclical_peak_risk", "valuation_triangulation", "valuation_upside_capped_pct")` in `stocks` table.

- [ ] **Step 1: Write the failing tests for schema migration and column definitions**

In `tests/test_store.py`:
```python
def test_schema_migration_adds_side_by_side_columns(tmp_path) -> None:
    db_path = tmp_path / "test_migration.db"
    store = SQLiteStore(db_path=db_path)
    with store._connect() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(stocks)")}
    assert "shares_insiders_percent" in cols
    assert "cyclical_peak_risk" in cols
    assert "valuation_triangulation" in cols
    assert "valuation_upside_capped_pct" in cols


def test_startup_backfill_populates_shares_insiders_percent(tmp_path) -> None:
    db_path = tmp_path / "test_backfill.db"
    store = SQLiteStore(db_path=db_path)
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO stocks (symbol, shares_insiders_pct) VALUES (?, ?)",
            ("TEST", 0.05),
        )
        conn.commit()
    # Re-instantiating triggers startup migration/backfill
    store._migrate_schema(store._connect())
    with store._connect() as conn:
        row = conn.execute(
            "SELECT shares_insiders_pct, shares_insiders_percent FROM stocks WHERE symbol='TEST'"
        ).fetchone()
    assert row[0] == 0.05
    assert row[1] == 5.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_store.py::test_schema_migration_adds_side_by_side_columns tests/test_store.py::test_startup_backfill_populates_shares_insiders_percent -v`
Expected: FAIL with missing column assertion error.

- [ ] **Step 3: Implement schema migration and backfill in `src/stonks/store.py` and `config.py`**

In `src/stonks/config.py`:
Add column display names:
```python
COLUMN_DISPLAY_NAMES: dict[str, str] = {
    ...
    "shares_insiders_pct": "Shares Insiders (Ratio)",
    "shares_insiders_percent": "Shares Insiders %",
    "cyclical_peak_risk": "Cyclical Peak Risk",
    "valuation_triangulation": "Valuation Consensus",
    "valuation_upside_capped_pct": "Upside (Capped %)",
}
```
Update `NUMERIC_FILTER_COLUMNS`:
Add `"shares_insiders_percent"`, `"cyclical_peak_risk"`, `"valuation_upside_capped_pct"`.
Update `ENUM_FILTER_COLUMNS`:
Add `"valuation_triangulation"`.
Update `VIEW_PRESETS["Quality"]` and `VIEW_PRESETS["Overview"]` to include the new columns.

In `src/stonks/store.py`:
Update `STOCK_FIELDS` and table schema to include the new columns.
In `_migrate_schema(conn)`:
```python
stock_columns = {row[1] for row in conn.execute("PRAGMA table_info(stocks)")}
new_cols = [
    ("shares_insiders_percent", "REAL"),
    ("cyclical_peak_risk", "INTEGER"),
    ("valuation_triangulation", "TEXT"),
    ("valuation_upside_capped_pct", "REAL"),
]
for col_name, col_type in new_cols:
    if col_name not in stock_columns:
        conn.execute(f"ALTER TABLE stocks ADD COLUMN {col_name} {col_type}")

# Backfill shares_insiders_percent from shares_insiders_pct if not yet populated
conn.execute("""
    UPDATE stocks
    SET shares_insiders_percent = shares_insiders_pct * 100.0
    WHERE shares_insiders_percent IS NULL AND shares_insiders_pct IS NOT NULL
""")
conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_store.py::test_schema_migration_adds_side_by_side_columns tests/test_store.py::test_startup_backfill_populates_shares_insiders_percent -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/stonks/store.py src/stonks/config.py tests/test_store.py
git commit -m "feat(store): expand schema with side-by-side metrics and backfill"
```

---

### Task 2: Backwards-Compatible `StockQueryResult` & Atomic Single-Connection Query Execution

**Files:**
- Modify: `src/stonks/store.py:770-820`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `store.get_stocks(...)`
- Produces: `StockQueryResult(tuple)` with `(rows, total_pages, total_matching)` and `.warnings`.

- [ ] **Step 1: Write the failing tests for `StockQueryResult` and atomic pagination**

In `tests/test_store.py`:
```python
def test_get_stocks_returns_stock_query_result_tuple(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.save_stock("AAPL", {"market_cap": 3000.0})
    result = store.get_stocks()
    # Verifies backwards compatibility as a 3-tuple
    rows, pages, total = result
    assert len(rows) == 1
    assert pages == 1
    assert total == 1
    assert hasattr(result, "warnings")
    assert isinstance(result.warnings, list)


def test_get_stocks_handles_zero_and_negative_page_size(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.save_stock("AAPL", {"market_cap": 3000.0})
    rows, pages, total = store.get_stocks(page_size=0)
    assert len(rows) == 1
    assert pages == 1
    rows_neg, pages_neg, total_neg = store.get_stocks(page_size=-10)
    assert len(rows_neg) == 1
    assert pages_neg == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_store.py::test_get_stocks_returns_stock_query_result_tuple tests/test_store.py::test_get_stocks_handles_zero_and_negative_page_size -v`
Expected: FAIL (ZeroDivisionError on page_size=0 or missing `.warnings`).

- [ ] **Step 3: Implement `StockQueryResult` and single-connection pagination in `src/stonks/store.py`**

In `src/stonks/store.py`:
Define `StockQueryResult`:
```python
class StockQueryResult(tuple):
    """3-tuple of (rows, total_pages, total_matching) with query diagnostic warnings."""

    rows: list[dict[str, Any]]
    total_pages: int
    total_matching: int
    warnings: list[str]

    def __new__(
        cls,
        rows: list[dict[str, Any]],
        total_pages: int,
        total_matching: int,
        warnings: list[str] | None = None,
    ) -> "StockQueryResult":
        instance = super().__new__(cls, (rows, total_pages, total_matching))
        instance.rows = rows
        instance.total_pages = total_pages
        instance.total_matching = total_matching
        instance.warnings = warnings or []
        return instance
```
In `get_stocks`:
```python
    page_size = max(1, min(int(page_size), 100_000))
    # Run COUNT(*) and SELECT in a single connection block
    with self._connect() as conn:
        total_matching = conn.execute(count_sql, params).fetchone()[0]
        total_pages = max(1, (total_matching + page_size - 1) // page_size)
        page = max(1, min(int(page), total_pages))
        offset = (page - 1) * page_size

        query_params = list(params)
        if sort_column and sort_column in numeric_columns:
            sort_dir = "ASC" if sort_ascending else "DESC"
            select_sql += f" ORDER BY {sort_column} {sort_dir} NULLS LAST"

        select_sql += " LIMIT ? OFFSET ?"
        query_params.extend([page_size, offset])

        cur = conn.execute(select_sql, query_params)
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    return StockQueryResult(rows, total_pages, total_matching, warnings=warnings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_store.py::test_get_stocks_returns_stock_query_result_tuple tests/test_store.py::test_get_stocks_handles_zero_and_negative_page_size -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/stonks/store.py tests/test_store.py
git commit -m "fix(store): atomic queries, safe LIMIT/OFFSET parameterization, and StockQueryResult"
```

---

### Task 3: Filter Validation Engine in `get_stocks`

**Files:**
- Modify: `src/stonks/store.py:690-730`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `filters: Mapping[str, Any]`
- Produces: Sanitized SQL clauses, zero matches on empty enum lists or inverted bounds, diagnostics in `result.warnings`.

- [ ] **Step 1: Write the failing tests for filter validation**

In `tests/test_store.py`:
```python
def test_unknown_filter_column_records_warning_and_skips(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.save_stock("AAPL", {"market_cap": 3000.0})
    result = store.get_stocks(filters={"non_existent_column": {"min": 10}})
    rows, _, total = result
    assert total == 1
    assert any("non_existent_column" in w for w in result.warnings)


def test_empty_enum_values_matches_zero_rows(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.save_stock("AAPL", {"exchange": "NMS"})
    result = store.get_stocks(filters={"symbol": {"values": []}})
    rows, _, total = result
    assert total == 0
    assert len(rows) == 0


def test_inverted_bounds_records_warning_and_matches_nothing(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.save_stock("AAPL", {"pe_ratio": 25.0})
    result = store.get_stocks(filters={"pe_ratio": {"min": 50, "max": 10}})
    rows, _, total = result
    assert total == 0
    assert any("min" in w and "max" in w for w in result.warnings)


def test_non_finite_numeric_bounds_ignored_with_warning(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.save_stock("AAPL", {"pe_ratio": 25.0})
    result = store.get_stocks(filters={"pe_ratio": {"min": float("nan")}})
    rows, _, total = result
    assert total == 1
    assert any("non-finite" in w.lower() for w in result.warnings)


def test_all_filter_and_sort_columns_exist_in_schema(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    with store._connect() as conn:
        schema_cols = {row[1] for row in conn.execute("PRAGMA table_info(stocks)")}
    from stonks.config import NUMERIC_FILTER_COLUMNS, ENUM_FILTER_COLUMNS
    assert set(NUMERIC_FILTER_COLUMNS) <= schema_cols
    assert set(ENUM_FILTER_COLUMNS) <= schema_cols
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_store.py::test_unknown_filter_column_records_warning_and_skips tests/test_store.py::test_empty_enum_values_matches_zero_rows tests/test_store.py::test_inverted_bounds_records_warning_and_matches_nothing -v`
Expected: FAIL.

- [ ] **Step 3: Implement filter validation in `src/stonks/store.py`**

In `src/stonks/store.py` within `get_stocks`:
```python
        warnings: list[str] = []
        if filters:
            for col, spec in filters.items():
                if not isinstance(spec, dict):
                    warnings.append(f"Invalid filter specification for '{col}': expected dict")
                    continue
                if col in numeric_columns:
                    min_val = spec.get("min")
                    max_val = spec.get("max")

                    parsed_min = None
                    parsed_max = None

                    if min_val is not None:
                        try:
                            fmin = float(min_val)
                            if math.isfinite(fmin):
                                parsed_min = fmin
                            else:
                                warnings.append(f"Ignored non-finite min bound on '{col}'")
                        except (ValueError, TypeError):
                            warnings.append(f"Ignored non-numeric min bound on '{col}'")

                    if max_val is not None:
                        try:
                            fmax = float(max_val)
                            if math.isfinite(fmax):
                                parsed_max = fmax
                            else:
                                warnings.append(f"Ignored non-finite max bound on '{col}'")
                        except (ValueError, TypeError):
                            warnings.append(f"Ignored non-numeric max bound on '{col}'")

                    if parsed_min is not None and parsed_max is not None and parsed_min > parsed_max:
                        warnings.append(f"Filter '{col}' has min ({parsed_min}) > max ({parsed_max}); matches 0 rows")
                        where_clauses.append("1=0")
                    else:
                        if parsed_min is not None:
                            where_clauses.append(f"{col} >= ?")
                            params.append(parsed_min)
                        if parsed_max is not None:
                            where_clauses.append(f"{col} <= ?")
                            params.append(parsed_max)

                elif col in enum_columns:
                    if "values" in spec:
                        values = spec["values"]
                        if not values:
                            where_clauses.append("1=0")
                        else:
                            placeholders = ",".join(["?"] * len(values))
                            where_clauses.append(f"{col} IN ({placeholders})")
                            params.extend(values)
                else:
                    warnings.append(f"Ignored unknown filter column: '{col}'")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_store.py::test_unknown_filter_column_records_warning_and_skips tests/test_store.py::test_empty_enum_values_matches_zero_rows tests/test_store.py::test_inverted_bounds_records_warning_and_matches_nothing tests/test_store.py::test_non_finite_numeric_bounds_ignored_with_warning tests/test_store.py::test_all_filter_and_sort_columns_exist_in_schema -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/store.py tests/test_store.py
git commit -m "fix(store): filter validation for unknown columns, empty enum lists, and inverted bounds"
```

---

### Task 4: Provider Data Ingestion for Side-by-Side Metrics

**Files:**
- Modify: `src/stonks/stockanalysis.py:110-180`
- Test: `tests/test_stockanalysis.py`

**Interfaces:**
- Consumes: StockAnalysis screener JSON payload
- Produces: Screener rows containing both `shares_insiders_pct` (fraction) and `shares_insiders_percent` (percentage).

- [ ] **Step 1: Write the failing tests for dual insider ownership columns**

In `tests/test_stockanalysis.py`:
```python
def test_build_rows_populates_both_insider_ownership_columns():
    rows = stockanalysis.build_rows(
        [{"symbol": "AAPL", "description": "Apple Inc.", "industry": "Hardware"}],
        {"AAPL": {"marketCap": 3000.0, "sharesInsiders": 3.897}},
    )
    aapl = rows[0]
    # Original fraction retained for reference benchmark checks
    assert aapl["shares_insiders_pct"] == pytest.approx(0.03897)
    # New true percentage column next to original
    assert aapl["shares_insiders_percent"] == pytest.approx(3.897)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_stockanalysis.py::test_build_rows_populates_both_insider_ownership_columns -v`
Expected: FAIL (`KeyError: 'shares_insiders_percent'`).

- [ ] **Step 3: Implement dual mapping in `src/stonks/stockanalysis.py`**

In `src/stonks/stockanalysis.py`:
Add to `DATA_POINT_MAP`:
```python
    "shares_insiders_pct": ("sharesInsiders", _fraction),
    "shares_insiders_percent": ("sharesInsiders", _identity),
```
In `build_rows`, ensure both keys are passed to row dicts.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_stockanalysis.py::test_build_rows_populates_both_insider_ownership_columns -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/stockanalysis.py tests/test_stockanalysis.py
git commit -m "feat(stockanalysis): ingest shares_insiders_percent alongside shares_insiders_pct"
```

---

### Task 5: Cyclicality Peak Detection & Valuation Triangulation Engine

**Files:**
- Modify: `src/stonks/config.py:75-95`
- Modify: `src/stonks/valuation.py:120-170`
- Modify: `src/stonks/stockanalysis.py:200-240`
- Test: `tests/test_valuation.py`

**Interfaces:**
- Consumes: `industry`, `ev_to_ebitda`, `roic_5y_avg_pct`, `fcf_growth_5y_pct`, `dcf_upside_pct`, `lynch_upside_pct`, `pt_upside_pct`, `peg_ratio`
- Produces: `cyclical_peak_risk: int`, `valuation_triangulation: str`, `valuation_upside_capped_pct: float | None`

- [ ] **Step 1: Write the failing tests for cyclical peak risk and valuation triangulation**

In `tests/test_valuation.py`:
```python
def test_evaluate_cyclical_peak_risk() -> None:
    # Cyclical industry with low multiple and high returns -> risk flagged
    assert valuation.evaluate_cyclical_peak_risk(
        industry="Gold",
        ev_to_ebitda=4.15,
        roic_5y_avg_pct=46.8,
        fcf_growth_5y_pct=15.0,
    ) == 1

    # Non-cyclical software company with low multiple -> not flagged
    assert valuation.evaluate_cyclical_peak_risk(
        industry="Software - Infrastructure",
        ev_to_ebitda=5.0,
        roic_5y_avg_pct=25.0,
        fcf_growth_5y_pct=15.0,
    ) == 0

    # Cyclical industry with high multiple -> not a peak-cycle trap
    assert valuation.evaluate_cyclical_peak_risk(
        industry="Semiconductors",
        ev_to_ebitda=15.0,
        roic_5y_avg_pct=30.0,
        fcf_growth_5y_pct=20.0,
    ) == 0


def test_evaluate_valuation_triangulation() -> None:
    # 3 models agree without cyclical risk -> Strong Consensus
    verdict, capped = valuation.evaluate_valuation_triangulation(
        dcf_upside=35.0,
        lynch_upside=28.0,
        pt_upside=22.0,
        peg_ratio=1.1,
        cyclical_risk=0,
    )
    assert verdict == "Strong Consensus"
    assert capped == pytest.approx(28.33, abs=0.1)

    # Cyclical peak stock with massive upside -> Cyclical Distorted
    verdict, capped = valuation.evaluate_valuation_triangulation(
        dcf_upside=338.0,
        lynch_upside=235.0,
        pt_upside=10.0,
        peg_ratio=0.5,
        cyclical_risk=1,
    )
    assert verdict == "Cyclical Distorted"
    assert capped == 150.0  # Display-capped at 150%

    # Single extreme model, other negative/missing -> Model Divergence / Outlier
    verdict, capped = valuation.evaluate_valuation_triangulation(
        dcf_upside=250.0,
        lynch_upside=None,
        pt_upside=-5.0,
        peg_ratio=2.5,
        cyclical_risk=0,
    )
    assert verdict == "Model Divergence / Outlier"
    assert capped == 150.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_valuation.py::test_evaluate_cyclical_peak_risk tests/test_valuation.py::test_evaluate_valuation_triangulation -v`
Expected: FAIL (`AttributeError: module 'stonks.valuation' has no attribute 'evaluate_cyclical_peak_risk'`).

- [ ] **Step 3: Implement cyclicality detection and triangulation in `valuation.py` & `stockanalysis.py`**

In `src/stonks/config.py`:
```python
CYCLICAL_INDUSTRIES: frozenset[str] = frozenset({
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
})
```

In `src/stonks/valuation.py`:
```python
from stonks.config import CYCLICAL_INDUSTRIES

def evaluate_cyclical_peak_risk(
    industry: object,
    ev_to_ebitda: object,
    roic_5y_avg_pct: object,
    fcf_growth_5y_pct: object,
) -> int:
    """Return 1 if stock is in a cyclical industry trading at peak multiple compression, 0 otherwise."""
    ind = str(industry or "")
    if ind not in CYCLICAL_INDUSTRIES:
        return 0
    ev = _number(ev_to_ebitda)
    roic = _number(roic_5y_avg_pct)
    fcf_g = _number(fcf_growth_5y_pct)
    if ev is None or ev >= 8.0:
        return 0
    if (roic is not None and roic > 20.0) or (fcf_g is not None and fcf_g > 25.0):
        return 1
    return 0


def evaluate_valuation_triangulation(
    dcf_upside: object,
    lynch_upside: object,
    pt_upside: object,
    peg_ratio: object,
    cyclical_risk: int,
) -> tuple[str, float | None]:
    """Classify valuation model consensus and compute capped display upside."""
    dcf = _number(dcf_upside)
    lynch = _number(lynch_upside)
    pt = _number(pt_upside)
    peg = _number(peg_ratio)

    valid_upsides = [u for u in (dcf, lynch, pt) if u is not None]
    if not valid_upsides:
        return "Unrated / Insufficient Data", None

    avg_upside = sum(valid_upsides) / len(valid_upsides)
    capped_upside = min(avg_upside, 150.0)

    if cyclical_risk == 1:
        return "Cyclical Distorted", capped_upside

    signals = sum([
        dcf is not None and dcf > 15.0,
        lynch is not None and lynch > 15.0,
        pt is not None and pt > 15.0,
        peg is not None and 0 < peg <= 1.5,
    ])

    if any(u > 150.0 for u in valid_upsides) and signals <= 1:
        return "Model Divergence / Outlier", capped_upside

    if signals >= 3:
        return "Strong Consensus", capped_upside
    if signals == 2:
        return "Moderate Value", capped_upside

    return "Single Model Only" if len(valid_upsides) == 1 else "Model Divergence / Outlier", capped_upside
```

In `src/stonks/stockanalysis.py` `build_rows`:
Compute `cyclical_peak_risk`, `valuation_triangulation`, and `valuation_upside_capped_pct` and set them on each row.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_valuation.py::test_evaluate_cyclical_peak_risk tests/test_valuation.py::test_evaluate_valuation_triangulation -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/config.py src/stonks/valuation.py src/stonks/stockanalysis.py tests/test_valuation.py
git commit -m "feat(valuation): add cyclical peak detection and valuation triangulation classification"
```

---

### Task 6: Background Worker Resilience & Sanity Check Drift

**Files:**
- Modify: `src/stonks/worker.py:110-155`
- Modify: `src/stonks/sanity.py:145-180`
- Test: `tests/test_worker.py`
- Test: `tests/test_sanity.py`

**Interfaces:**
- Consumes: Worker job loop and sanity checks
- Produces: Persisted sync status in metadata, metric drift assertions in `check_stockanalysis`.

- [ ] **Step 1: Write the failing tests for sync metadata and sanity checks**

In `tests/test_worker.py`:
```python
def test_job_persists_failure_metadata_on_exception(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    def fail_fetch(*args, **kwargs):
        raise ConnectionError("StockAnalysis timeout")
    monkeypatch.setattr(worker, "fetch_rows", fail_fetch)

    worker.job()
    assert store.get_metadata("last_sync_status") == "failed"
    assert "StockAnalysis timeout" in store.get_metadata("last_sync_error")


def test_job_persists_success_metadata(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    monkeypatch.setattr(worker, "SQLiteStore", lambda: store)
    monkeypatch.setattr(worker, "fetch_rows", lambda *a, **k: [{"symbol": "AAPL", "market_cap": 100.0}])
    monkeypatch.setattr(worker, "fetch_largest_buys", lambda: set())

    worker.job()
    assert store.get_metadata("last_sync_status") == "success"
    assert store.get_metadata("last_successful_sync_at") is not None
```

In `tests/test_sanity.py`:
```python
def test_stockanalysis_sanity_check_asserts_under_100k_rows(monkeypatch, tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    monkeypatch.setattr(sanity, "default_screen", lambda: {"filters": {}})
    monkeypatch.setattr(sanity, "fetch_rows", lambda *a, **k: [{"symbol": f"S{i}", "market_cap": 1.0} for i in range(10)])
    result = sanity.check_stockanalysis(store)
    assert result.ok is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_worker.py::test_job_persists_failure_metadata_on_exception tests/test_worker.py::test_job_persists_success_metadata -v`
Expected: FAIL (metadata not set).

- [ ] **Step 3: Implement sync metadata persistence and sanity guards**

In `src/stonks/worker.py`:
Wrap `job()` execution to record status:
```python
def job() -> None:
    logger.info("🚀 Starting data sync...")
    store = SQLiteStore()
    now_ts = str(time.time())
    try:
        store.prune_alerts()
        watched = set(store.get_watchlist_symbols())
        previous = _watched_rows(store, watched)

        discount_rate = current_discount_rate()
        rows = fetch_rows(discount_rate=discount_rate)
        if not rows:
            logger.warning("⚠️ No screener data found.")
            store.save_metadata("last_sync_status", "failed")
            store.save_metadata("last_sync_time", now_ts)
            store.save_metadata("last_sync_error", "No screener data returned from provider")
            return

        largest_buys = fetch_largest_buys()
        if largest_buys is not None:
            apply_flags(rows, largest_buys)

        store.replace_stocks(rows)
        store.save_metadata("universe_size", len(rows))
        store.save_metadata("last_sync_status", "success")
        store.save_metadata("last_sync_time", now_ts)
        store.save_metadata("last_successful_sync_at", now_ts)
        store.save_metadata("last_sync_error", "")

        _record_change_alerts(store, watched, previous, rows)
        fetch_watched_news(store, sorted(watched))
        _maybe_run_sanity_checks(store)
        logger.info("✅ Synced %s symbols", len(rows))
    except Exception as exc:
        logger.exception("💥 Critical error")
        store.save_metadata("last_sync_status", "failed")
        store.save_metadata("last_sync_time", now_ts)
        store.save_metadata("last_sync_error", str(exc))
```

In `src/stonks/sanity.py`:
In `check_stockanalysis`:
Assert `total < 100_000` to prevent silent page truncation.
Add spot-checking of overlapping symbols across numeric columns within 2% relative tolerance.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_worker.py::test_job_persists_failure_metadata_on_exception tests/test_worker.py::test_job_persists_success_metadata -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/worker.py src/stonks/sanity.py tests/test_worker.py tests/test_sanity.py
git commit -m "feat(worker,sanity): persist sync health metadata and guard sanity truncation"
```

---

### Task 7: UI Bug Fixes & Presentation Enhancements

**Files:**
- Modify: `src/stonks/app.py:820-880, 1020-1160`
- Test: `tests/test_header_ui.py` or new `tests/test_screener_ui.py`

**Interfaces:**
- Consumes: `StockQueryResult.warnings`, `store.get_metadata("last_sync_status")`
- Produces: Sanitized HTML bold tags, pruned filters, unified screen state applicator, sync alert banner, cyclical peak badges.

- [ ] **Step 1: Write tests for UI filter pruning, HTML tag escaping, and screen state**

Create `tests/test_screener_ui.py`:
```python
from stonks.app import _prune_filters, _format_filter_tags


def test_prune_filters_removes_empty_bounds_and_values() -> None:
    raw = {
        "pe_ratio": {"min": None, "max": None},
        "exchange": {"values": []},
        "market_cap": {"min": 1000},
        "valid_enum": {"values": ["NYSE"]},
    }
    pruned = _prune_filters(raw)
    assert "pe_ratio" not in pruned
    assert "exchange" not in pruned
    assert pruned["market_cap"] == {"min": 1000}
    assert pruned["valid_enum"] == {"values": ["NYSE"]}


def test_format_filter_tags_closes_strong_tags_safely() -> None:
    parts = ["**P/E**: ≥ 10, ≤ 25", "**Symbol**: ∈ ['AAPL', '<script>']"]
    html_output = _format_filter_tags(parts)
    assert "<strong>P/E</strong>" in html_output
    assert "<script>" not in html_output  # Safely escaped
    assert "&lt;script&gt;" in html_output
    assert html_output.count("<strong>") == html_output.count("</strong>")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_screener_ui.py -v`
Expected: FAIL (`ImportError: cannot import name '_prune_filters'`).

- [ ] **Step 3: Implement UI helpers and fixes in `src/stonks/app.py`**

In `src/stonks/app.py`:
1. Implement `_prune_filters(filters: dict[str, Any]) -> dict[str, Any]`.
2. Implement `_format_filter_tags(parts: list[str]) -> str` using `html.escape` and `re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)`.
3. Implement `apply_screen_state(screen: dict[str, Any]) -> None` with default `sort_ascending = screen.get("sort_ascending", True)`.
4. In `render_screener_table`:
   - Surface warnings if `page_rows.warnings` is non-empty:
     ```python
     if hasattr(page_rows, "warnings") and page_rows.warnings:
         st.warning("\n".join(f"⚠️ {w}" for w in page_rows.warnings))
     ```
   - Surface background sync failure/staleness banner if `store.get_metadata("last_sync_status") == "failed"`.
   - Update active filters HTML rendering to use `_format_filter_tags`.
   - Render ⚠️ badge for `cyclical_peak_risk == 1` and display `valuation_triangulation` alongside upside metrics.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_screener_ui.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stonks/app.py tests/test_screener_ui.py
git commit -m "fix(ui): HTML tag replacement, filter pruning, and sync staleness banner"
```

---

### Task 8: Full Test Suite & Benchmark Regression Run

**Files:**
- Run: Complete pytest suite

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/pytest -v`
Expected: All tests pass (including `test_sanity.py`, `test_stockanalysis.py`, `test_valuation.py`, `test_hedgefollow.py`).

- [ ] **Step 2: Commit final cleanup and documentation**

```bash
git commit -m "chore: complete test suite and sanity benchmark verification"
```
