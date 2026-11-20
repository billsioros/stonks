# Yahoo Migration Minor Fixes — Design

## Intent

Close the deferred items from the Yahoo screener migration and prove that existing screener features still work.

## Goals

- Multiple enum prefilter values select the union, not the intersection.
- Annual growth metrics use the requested lookback window even when more history is available.
- Malformed Yahoo quotes without a symbol are skipped.
- Every displayable/filterable column in the UI is either populated from Yahoo data or removed from the UI surface.
- Regression tests cover provider mapping/derivation, config consistency, preset applicability, and existing SQLiteStore features.

## Non-goals

- No new data provider, schema migration, UI redesign, or DCF/Peter Lynch/HedgeFollow work.
- No push or merge to master.

## Constraints

- Keep `SQLiteStore.get_stocks` signature unchanged.
- Keep all 9 `POPULAR_SCREENS` applicable without UI edits.
- Missing provider data remains `NULL`; never fabricate values.
- Use `uv run` for all Python commands; ruff is now a dev dependency installed with uv.
- Work only on `feature/yahoo-migration-minors`.

## Decisions

- Enum values are wrapped in one `EquityQuery("or", ...)` operand.
- `_cagr_from_series` starts at `ordered.iloc[-(years + 1)]` when enough points exist.
- `normalize_quote` returns `{}` when `symbol` is missing/blank; `paginate` skips empty rows.
- Derive the remaining schema-backed columns from Yahoo `info`, monthly history, and annual statements:
  - `type` from quote `quoteType`.
  - `industry` from `info["industry"]`.
  - `pt_upside_pct` from `info["targetMeanPrice"]` vs `info["currentPrice"]` / `regularMarketPrice`.
  - `fcf_margin_pct` from latest FCF / latest revenue.
  - `eps_growth_3y_pct` from 3Y EPS CAGR.
  - `free_cash_flow_per_share` and `revenue_per_share` from latest annual values / shares outstanding.
  - `long_term_debt_to_equity` from latest long-term debt / equity.
  - `asset_turnover` from latest revenue / average total assets.
- Remove display-only columns with no backing store column (`total_debt_to_total_equity`, `inventory_turnover`, `receivables_turnover`) from `COLUMN_DISPLAY_NAMES`.
- `enrich_rows` merges all non-`None` derived values, not only the requested columns, so UI columns are persisted; existing row values are never overwritten by `None`.

## Verification

- `uv run pytest -q`
- `uv run ruff check src tests`
- `uv run python -c "from stonks.app import app; print('app import ok')"`
- All pre-commit hooks pass on each commit.
