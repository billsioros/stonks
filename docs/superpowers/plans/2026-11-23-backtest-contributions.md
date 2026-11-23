# Backtest Contributions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the portfolio backtest use fixed per-ticker sums and recurring contributions, with a choice of rebalancing or drift and return metrics that survive cash flows.

**Architecture:** Extend the existing engine's `simulate`/`run_backtest` with per-symbol contributions and a contribution cadence, while deriving time-weighted performance from an internal growth index instead of the deposit-inflated account curve. The Streamlit view maps its allocation mode and contribution inputs onto those engine arguments; saved settings gain backwards-compatible keys.

**Tech Stack:** Python 3.13, pytest, Streamlit, pandas, SQLite via `stonks.store`.

**Spec:** `docs/superpowers/specs/2026-11-23-backtest-contributions-design.md`

## Global Constraints

- No FX conversion; amounts and prices are plain currency units.
- Month-end adjusted closes and the ten-year window stay unchanged.
- Defaults: percentages, initial 10,000, contribution off, monthly cadence, annual rebalance.
- Existing saved portfolios (JSON without the new keys) must still load and run.
- Existing behaviour without contributions must keep its current numbers.

## Review Focus

- First month with `initial=0`: the first contribution must be invested at month zero, never divide by a zero starting value — Task 1 test.
- Deposit-inflated statistics: time-weighted CAGR, drawdown and yearly returns must ignore the deposit schedule — Task 1 test.
- Rebalance on a contribution month: deposit first, then reset to target weights — Task 1 test.
- Benchmark fairness: benchmark must receive the same initial amount and contribution schedule — Task 2 test.
- Old saved settings: missing new keys must fall back to the defaults — Task 3 test.

---

### Task 1: Engine simulation with contributions

**Files:**
- Modify: `src/stonks/backtest.py` (constants near lines 32-45, `simulate` at 125-199)
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `prices: dict[str, dict[str, float]]`, `weights: dict[str, float]`, `REBALANCE_MONTHS`.
- Produces: `CONTRIBUTION_MONTHS: dict[str, int]` keys `none/monthly/quarterly/semiannual/annual` with values `0/1/3/6/12`; `simulate(prices, weights, *, rebalance="annual", initial=10_000.0, contributions: dict[str, float] | None = None, frequency: str = "none") -> dict[str, Any]`. Result gains `contribution` (sum per contribution), `frequency`, `invested`, `gain`, `money_weighted_cagr_pct` (float or `None`). Existing keys keep their meaning; `total_return_pct`/`cagr_pct`/`stdev_pct`/`max_drawdown_pct`/`yearly` become time-weighted.

- [ ] **Step 1: Add failing tests** to `tests/test_backtest.py` (import `CONTRIBUTION_MONTHS`, `simulate`):

```python
def test_contributions_buy_at_month_zero_and_accumulate() -> None:
    months = _months(2020, 4)
    result = simulate(
        {"A": dict.fromkeys(months, 100.0)},
        {"A": 1.0},
        initial=0.0,
        contributions={"A": 100.0},
        frequency="monthly",
    )
    assert "error" not in result
    assert result["invested"] == 400.0
    assert [point["value"] for point in result["curve"]] == [100.0, 200.0, 300.0, 400.0]
    assert result["cagr_pct"] == pytest.approx(0.0)


def test_contributions_keep_time_weighted_stats_independent_of_deposits() -> None:
    months = _months(2020, 25)
    prices = {
        "A": {month: 100.0 if index < 12 else 50.0 for index, month in enumerate(months)}
    }
    result = simulate(
        prices,
        {"A": 1.0},
        initial=0.0,
        contributions={"A": 100.0},
        frequency="monthly",
        rebalance="none",
    )
    assert result["max_drawdown_pct"] == pytest.approx(-50.0)
    assert result["cagr_pct"] < 0
    assert result["invested"] == 2500.0


def test_rebalance_happens_after_contribution() -> None:
    months = _months(2020, 3)
    prices = {
        "A": dict.fromkeys(months, 100.0),
        "B": {month: 100.0 * 1.1**index for index, month in enumerate(months)},
    }
    kwargs = {
        "initial": 0.0,
        "contributions": {"A": 60.0, "B": 40.0},
        "frequency": "monthly",
    }
    drift = simulate(prices, {"A": 60.0, "B": 40.0}, rebalance="none", **kwargs)
    rebalanced = simulate(prices, {"A": 60.0, "B": 40.0}, rebalance="monthly", **kwargs)
    assert rebalanced["final"] < drift["final"]


def test_money_weighted_return_reflects_contribution_timing() -> None:
    months = _months(2020, 13)
    prices = {"A": {month: 100.0 if index < 12 else 200.0 for index, month in enumerate(months)}}
    result = simulate(
        prices,
        {"A": 1.0},
        initial=0.0,
        contributions={"A": 100.0},
        frequency="monthly",
    )
    assert result["money_weighted_cagr_pct"] is not None
    assert 0 < result["money_weighted_cagr_pct"] < result["cagr_pct"]
    assert simulate(prices, {"A": 1.0})["money_weighted_cagr_pct"] is None


def test_simulate_rejects_bad_contribution_inputs() -> None:
    prices = {"A": dict.fromkeys(_months(2020, 3), 100.0)}
    assert "error" in simulate(prices, {"A": 1.0}, frequency="weekly")
    assert "error" in simulate(prices, {"A": 1.0}, contributions={"A": -1.0})
    assert "error" in simulate(prices, {"A": 1.0}, initial=0.0)
    assert "error" in simulate(
        prices, {"A": 1.0}, initial=0.0, contributions={"A": 1.0}, frequency="none"
    )
```

- [ ] **Step 2: Run `pytest tests/test_backtest.py -q` and confirm the new tests fail** on missing `CONTRIBUTION_MONTHS`/unexpected result keys.

- [ ] **Step 3: Implement in `src/stonks/backtest.py`.** Add `CONTRIBUTION_MONTHS = dict(REBALANCE_MONTHS)`. In `simulate`, validate inputs (known frequency, non-negative initial/contributions, some money to invest, contributions only with a cadence), normalise targets, invest `initial + first contribution` at the first month, and on each later month: compute the account value from prior units, multiply a growth index by `value / previous_value`, add that month's contribution when `index % step == 0`, then rebalance when `index % every == 0`. Derive `total_return_pct`, `cagr_pct`, `stdev_pct`, `max_drawdown_pct` and `yearly` from the growth-index series; keep the account-value series in `curve` and `final`. Compute `invested`, `gain` and `money_weighted_cagr_pct` by solving the monthly IRR of the dated cash flows with bisection over `[-0.9999, upper]`, doubling `upper` until the NPV changes sign; return `None` when no bracket exists or no contributions were made.

- [ ] **Step 4: Run `pytest tests/test_backtest.py -q` and confirm all tests pass**, including the pre-existing lump-sum tests.

- [ ] **Step 5: Commit** with `git add src/stonks/backtest.py tests/test_backtest.py && git commit -m "feat: model recurring contributions in backtest engine"`.

### Task 2: Thread contributions through run_backtest and the benchmark

**Files:**
- Modify: `src/stonks/backtest.py` (`_benchmark_result` at 202-245, `run_backtest` at 248-320)
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `simulate(..., contributions=..., frequency=...)` from Task 1.
- Produces: `run_backtest(store, symbols, weights=None, *, rebalance="annual", start=None, end=None, initial=10_000.0, benchmark=None, contributions: list[float] | None = None, frequency: str = "none", fetch=None) -> dict[str, Any]`; result carries `contributions` as a per-symbol dict, `contribution`, `frequency`, `invested`, `gain`, `money_weighted_cagr_pct`; benchmark uses the same cash flows.

- [ ] **Step 1: Add failing test** to `tests/test_backtest.py`:

```python
def test_run_backtest_gives_benchmark_the_same_contributions(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    months = _months(2020, 13)
    prices = {month: 100.0 for month in months}
    store.cache_set("hist:AAA:10Y:Monthly", prices, 3600)
    store.cache_set("hist:BMB:10Y:Monthly", prices, 3600)

    result = run_backtest(
        store,
        ["AAA"],
        contributions=[100.0],
        frequency="monthly",
        initial=0.0,
        benchmark="BMB",
    )
    assert "benchmark_error" not in result
    assert result["benchmark"]["final"] == pytest.approx(result["final"])
    assert result["benchmark"]["cagr_pct"] == pytest.approx(result["cagr_pct"])
    assert result["invested"] == 1300.0


def test_run_backtest_rejects_mismatched_contributions(tmp_path) -> None:
    store = SQLiteStore(db_path=tmp_path / "test.db")
    store.cache_set("hist:AAA:10Y:Monthly", {"2020-01": 1.0, "2020-02": 2.0}, 3600)
    assert "error" in run_backtest(store, ["AAA"], contributions=[1.0, 2.0])
```

- [ ] **Step 2: Run `pytest tests/test_backtest.py -q` and confirm the two new tests fail.**

- [ ] **Step 3: Implement.** Extend `run_backtest`'s signature above; de-duplicate symbols first, then reject a contributions list whose length differs from the unique symbols. Map contributions onto symbols by position and pass them plus `frequency` to `simulate`, then echo the fields onto the result. Extend `_benchmark_result` with `initial`, `contribution` (total), `contributions` (per-symbol dict), and `frequency`; simulate the benchmark with one symbol whose contribution is the portfolio's total per contribution, so its cash-flow timing matches. Copy the new money-weighted fields into the benchmark result dict.

- [ ] **Step 4: Run `pytest tests/test_backtest.py -q` and confirm all tests pass.**

- [ ] **Step 5: Commit** with `git add src/stonks/backtest.py tests/test_backtest.py && git commit -m "feat: carry contributions through backtest benchmark"`.

### Task 3: Backtest inputs, parsing and saved settings

**Files:**
- Modify: `src/stonks/backtest_view.py` (constants 23-38, parsing 75-151, settings summary 163-174, form 389-491)
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `run_backtest(..., contributions=..., frequency=...)` from Task 2; `CONTRIBUTION_MONTHS` from Task 1.
- Produces: `parse_portfolio(rows: list[dict[str, Any]], mode: str = "percent") -> tuple[list[str], list[float] | None]` accepting `Allocation`, `Amount` and legacy `Weight %` row keys; `default_settings()` with `allocation_mode`, `contribution`, `contribution_frequency`; `_settings_from_widgets(...)` and `_portfolio_rows(settings)` round-tripping those keys.

- [ ] **Step 1: Add failing tests** to `tests/test_backtest.py`:

```python
def test_parse_portfolio_amount_mode_requires_every_amount() -> None:
    rows = [{"Allocation": "vuaa", "Amount": 600}, {"Allocation": "NVDA", "Amount": 400}]
    assert parse_portfolio(rows, mode="amount") == (["VUAA", "NVDA"], [600.0, 400.0])
    with pytest.raises(ValueError):
        parse_portfolio([{"Allocation": "VUAA", "Amount": 600}, {"Allocation": "NVDA"}], mode="amount")


def test_new_settings_round_trip_and_old_settings_default() -> None:
    settings = default_settings()
    assert settings["allocation_mode"] == "percent"
    assert settings["contribution"] == 0.0
    assert settings["contribution_frequency"] == "monthly"
    rows = _portfolio_rows(settings)
    assert "Allocation" in rows[0]
    legacy = {"symbols": ["AAA"], "weights": [60.0], "benchmark": "", "rebalance": "none"}
    assert _portfolio_rows(legacy)[0]["Allocation"] == 60.0
```

- [ ] **Step 2: Run `pytest tests/test_backtest.py -q` and confirm the new tests fail.**

- [ ] **Step 3: Implement.** Use a stable `Allocation` dataframe column with a dynamic label ("Weight %" or "Amount per contribution"). Add radio/selectbox widgets for mode, contribution amount (min 0) and cadence using `CONTRIBUTION_MONTHS`; add their keys to `_WIDGET_KEYS`. In amount mode require positive values on every row; in percent mode preserve blank-means-equal and forbid zero/negative. Allow `initial` to be zero and reject the case where nothing at all is invested. Build per-symbol contributions from the chosen amounts (amount mode) or from the total contribution split by weights (percent mode, equal split when blank), and pass `weights`, `contributions`, `frequency` to `run_backtest` and set `result["allocation_mode"] = current["allocation_mode"]` before storing the result. Store `allocation_mode`, `contribution`, `contribution_frequency` in the settings dict; keep existing `weights` as the generic allocation list. Update `_describe_settings` to name amounts and cadence, and make loaded settings fill missing new keys from `default_settings()`.

- [ ] **Step 4: Run `pytest tests/test_backtest.py -q` and confirm all tests pass.**

- [ ] **Step 5: Commit** with `git add src/stonks/backtest_view.py tests/test_backtest.py && git commit -m "feat: add fixed-amount and contribution inputs to backtest tab"`.

### Task 4: Result display for contribution runs

**Files:**
- Modify: `src/stonks/backtest_view.py` (`_render_result` at 252-350)
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: result keys from Tasks 1-3.
- Produces: `format_allocation(result: dict[str, Any]) -> str` pure helper returning the caption's allocation text for both modes.

- [ ] **Step 1: Add failing test** to `tests/test_backtest.py`:

```python
def test_format_allocation_for_both_modes() -> None:
    assert format_allocation({"allocation_mode": "amount", "contributions": {"VUAA": 600.0, "NVDA": 400.0}}) == "VUAA 600 · NVDA 400 per contribution"
    assert format_allocation({"weights": {"VUAA": 60.0, "NVDA": 40.0}}) == "VUAA 60% · NVDA 40%"
```

- [ ] **Step 2: Run `pytest tests/test_backtest.py -q` and confirm the test fails.**

- [ ] **Step 3: Implement.** Add `format_allocation(result)` using `allocation_mode` and `contributions` when present, otherwise the existing `weights` formatting. Use it in the caption; show the contribution cadence and total invested, replace the `$... invested` wording with `invested` from the result, show a `Total invested` pill and a `Money-weighted` pill when contributions are active, and keep CAGR/total return labelled as time-weighted. Note in the closing caption that returns are time-weighted.

- [ ] **Step 4: Run `pytest tests/test_backtest.py -q` and confirm all tests pass.**

- [ ] **Step 5: Commit** with `git add src/stonks/backtest_view.py tests/test_backtest.py && git commit -m "feat: show invested capital and money-weighted return"`.

### Task 5: Documentation and whole-suite verification

**Files:**
- Modify: `README.md` (backtest feature description near line 29)
- Test: full suite

- [ ] **Step 1: Update the backtest description** to mention fixed sums, recurring contributions and rebalance-or-drift, while stating that amounts are not currency-converted.

- [ ] **Step 2: Run `uv run ruff check .`, `uv run mypy src` and `uv run pytest -q`; fix any failures they reveal.**

- [ ] **Step 3: Run a Streamlit AppTest smoke check** via `pytest tests/test_backtest_ui.py -q` and confirm no exception.

- [ ] **Step 4: Commit** with `git add README.md && git commit -m "docs: describe backtest contributions"`.
