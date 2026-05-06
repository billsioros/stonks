# CHANGELOG

<!-- version list -->

## v2.2.0 (2026-05-06)

### Features

- Integrate analyst recommendations, price targets, and company profiles into data pipeline and UI
  ([`819e0d8`](https://github.com/billsioros/stonks/commit/819e0d8ee9bbc8885a4bdb7addcbf6a6a4d76426))


## v2.1.0 (2026-05-06)

### Features

- Add comprehensive financial metrics and implement robust derivation logic for missing data points
  ([`7ced3a4`](https://github.com/billsioros/stonks/commit/7ced3a4df82dc226e8195658890cc869cf4d209d))

### Refactoring

- Remove unused summary metric cards from the main dashboard view
  ([`9aaa04b`](https://github.com/billsioros/stonks/commit/9aaa04b218014e15a2148024906494a4ac467af4))


## v2.0.0 (2026-04-29)

### Features

- Refactor MetricsProvider and SQLiteStore, enhance job synchronization logic
  ([`968f9fa`](https://github.com/billsioros/stonks/commit/968f9fa717ffe25749006e716ab9bc1752a94ba6))


## v1.1.2 (2026-04-26)

### Bug Fixes

- Remove caching layer and engine class, and add persistent stock storage schema
  ([`e8f500b`](https://github.com/billsioros/stonks/commit/e8f500bfcade4675b79979a1598de7e03f1cbe3d))


## v1.1.1 (2026-04-20)

### Bug Fixes

- Remove unused filter variables and ignore mypy cache files
  ([`b7ab6ce`](https://github.com/billsioros/stonks/commit/b7ab6ce3fe1fd2782af4465e62d850409daf9fa6))


## v1.1.0 (2026-04-20)

### Bug Fixes

- Upgrade uv to 0.9.0 and update dependency installation to include dev group in CI
  ([`241400c`](https://github.com/billsioros/stonks/commit/241400ce1f81edf7baf67c7486187dee0cf77971))

### Features

- Migrate sidebar filters to a grid-based top-level filter UI and remove redundant dataset loading
  logic
  ([`e7731dd`](https://github.com/billsioros/stonks/commit/e7731dd2bbf1380b5caf2bd6ffd37a898efd4dd6))


## v1.0.2 (2026-04-20)

### Bug Fixes

- Remove dev group from uv dependency installation in CI workflow
  ([`bebec3c`](https://github.com/billsioros/stonks/commit/bebec3c9aa80eca524078f86264568ebc5ecbf4f))


## v1.0.1 (2026-04-20)

### Bug Fixes

- **ci**: Explicitly include dev group for pytest
  ([`a38931c`](https://github.com/billsioros/stonks/commit/a38931c97bdb3bcfe86c0f5c535f8f60ee137b03))


## v1.0.0 (2026-04-20)

- Initial Release
