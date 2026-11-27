# CHANGELOG

<!-- version list -->

## v2.11.0 (2026-11-27)

### Bug Fixes

- Left-align news notification article links
  ([`9ead4d1`](https://github.com/billsioros/stonks/commit/9ead4d16fa402f23773870c0ac393696bac25062))

- Show all unread alerts in notifications
  ([`9f64571`](https://github.com/billsioros/stonks/commit/9f645715afdbbab3eb6dc779b9bc69eaa13d8fc0))

- Stop reporting HedgeFollow outages as divergences
  ([`66f73e9`](https://github.com/billsioros/stonks/commit/66f73e9e289791506a3537f4eaaa41996d8f89fe))

### Chores

- Clean up working tree tracking
  ([`6c58cb1`](https://github.com/billsioros/stonks/commit/6c58cb114206e9e91fa45ef33397dd2115599bbd))

### Features

- Link news notification headlines to articles
  ([`f0263f4`](https://github.com/billsioros/stonks/commit/f0263f4f92a20c93386adc934f93f629e8c96f4a))

- Mark a symbol's notifications seen from its card header
  ([`c258558`](https://github.com/billsioros/stonks/commit/c258558a400f66939400709fe63dabe87ba2118d))

- Mark individual notifications as seen
  ([`50bfc0f`](https://github.com/billsioros/stonks/commit/50bfc0fe6d7366ac74adcd32e414a8f2a6ae779e))

- Source notifications only from stored alerts
  ([`e97fe39`](https://github.com/billsioros/stonks/commit/e97fe396736a0f7809b9aeca9bbd3494973a3632))

- Store every near-52-week-low opportunity as an alert
  ([`641c726`](https://github.com/billsioros/stonks/commit/641c72686451bf4245bdebcb54f0ce7fabcd841f))


## v2.10.0 (2026-11-26)

### Bug Fixes

- Correct daily P&L headline and watchlist ETF news
  ([`6d99e03`](https://github.com/billsioros/stonks/commit/6d99e03a05dad0f4ce0fb3ffcf8eb86f4502a811))

- Exclude unpriced holdings from portfolio USD totals
  ([`0190153`](https://github.com/billsioros/stonks/commit/019015396f3e490a5f9e1395559a1ef05cc9c93d))

- Preserve held quotes outside the screener universe
  ([`e0f35d5`](https://github.com/billsioros/stonks/commit/e0f35d52090d34586fbaae3cfce335b98fd752fe))

- Restore direct entry point and isolate portfolio test patches
  ([`54344a3`](https://github.com/billsioros/stonks/commit/54344a3127322a6d80468830ecb8eb751cc69c12))

- Restrict portfolio lots to USD and EUR
  ([`5227b8d`](https://github.com/billsioros/stonks/commit/5227b8dd945b86dbdeb82460a5b25741b3b40a62))

### Features

- Add candidate and portfolio correlation helpers
  ([`80614e8`](https://github.com/billsioros/stonks/commit/80614e8f05194b5493a8f8209655ee79f7e8c9b5))

- Add portfolio tab with lot editor and quick backtest
  ([`cfb6db4`](https://github.com/billsioros/stonks/commit/cfb6db4a0a6669ac371656c560364326b17fb784))

- Add portfolio valuation and FX helpers
  ([`81d7386`](https://github.com/billsioros/stonks/commit/81d7386bb2d857c617ce9f71083d27e46c7fc2b9))

- Alert portfolio holdings outside the watchlist
  ([`7623aeb`](https://github.com/billsioros/stonks/commit/7623aeb06dac81a7cc9c552c24221a1ed693ac6e))

- Default backtest contribution to 500 euros
  ([`f28a89a`](https://github.com/billsioros/stonks/commit/f28a89addb525d318ae5bf7d1b81f37576133961))

- Flag screener candidates correlated with the portfolio
  ([`ab32e4c`](https://github.com/billsioros/stonks/commit/ab32e4c8df655dbb41beb3f23ed570273c22b7b7))

- Persist portfolio lots in SQLite
  ([`a866c7b`](https://github.com/billsioros/stonks/commit/a866c7b8cdef0ee85fb5a2d7f3715214c964ce94))

- Run holdings backtests with dual benchmarks and correlation
  ([`337e47b`](https://github.com/billsioros/stonks/commit/337e47bc6a5e9812c0209c74028e0364028e1981))

- Show EUR portfolio headlines and color correlation by level
  ([`1927c0d`](https://github.com/billsioros/stonks/commit/1927c0d582d630d3f30eb48fb59291cb7e7e651d))

- Surface portfolio alerts in notifications
  ([`1a1f230`](https://github.com/billsioros/stonks/commit/1a1f23015c03b70a3479cf70ea899dcc62c42bb0))


## v2.9.0 (2026-11-25)

### Features

- Group watchlist notifications by symbol
  ([`c7d0d4d`](https://github.com/billsioros/stonks/commit/c7d0d4d0d7a752f83a73cca7a25554fd6b6676eb))


## v2.8.0 (2026-11-25)

### Features

- Add failure-aware sync cadence and UI polish
  ([`ed1fc78`](https://github.com/billsioros/stonks/commit/ed1fc78279200eb84def29b3f80c1db2d045c03d))


## v2.7.0 (2026-11-24)

### Features

- Close gaps and deferred minors follow-up
  ([`f0bf31f`](https://github.com/billsioros/stonks/commit/f0bf31f8fb707b01bb61ed30653736a36b466c05))


## v2.6.0 (2026-11-24)

### Bug Fixes

- Close final review filing-verification gaps
  ([`7ef8a52`](https://github.com/billsioros/stonks/commit/7ef8a52ee927aadb9f2332105ac13d52853ec468))

- Close remaining deep-dive review minors
  ([`23990bf`](https://github.com/billsioros/stonks/commit/23990bfb63f951128c3c22068a9b38c04ca1d139))

- Fall back through XBRL tag aliases in filing checks
  ([`b0dac9e`](https://github.com/billsioros/stonks/commit/b0dac9ee8250a4881c298c1b5c36fdc21c327fe8))

- Harden sync failures, sanity checks, and dossier minors
  ([`0fc60ba`](https://github.com/billsioros/stonks/commit/0fc60baaa1ed82f0659f87671da272ab64692301))

- Keep known failures, carry filing conflicts, scope EFTS sweep
  ([`18b8927`](https://github.com/billsioros/stonks/commit/18b8927c3454f3fe2c4d918200054e8f0d032998))

- Make deep-dive gates and masthead badges trustworthy
  ([`2a5a138`](https://github.com/billsioros/stonks/commit/2a5a1383d0a39680475fc8801da9de87e457c1b8))

- Pass the local environment file into the containers
  ([`09d2242`](https://github.com/billsioros/stonks/commit/09d2242cb9a528268bb08e225f369d803b7822cd))

- Remove redundant data-source line from masthead
  ([`cd65abb`](https://github.com/billsioros/stonks/commit/cd65abb8d22e2387445987c5c9fecf8ae7eebdd9))

### Documentation

- Plan Phase B EDGAR filing verification
  ([`0576dc4`](https://github.com/billsioros/stonks/commit/0576dc40b64d35ddb5d0e63b936628eca9d5ee06))

### Features

- Add a keyless, rate-limited EDGAR client
  ([`45f8fd6`](https://github.com/billsioros/stonks/commit/45f8fd6fbfcb09ccb4cc6bcaa8d843d7629d9de9))

- Add buy-opportunity alerts and deepen dossier checks
  ([`d132127`](https://github.com/billsioros/stonks/commit/d1321277f8aaa9602948ccab57a5176485fa43ff))

- Add the forward-evidence gate and trailing-only guard
  ([`ff5a9f1`](https://github.com/billsioros/stonks/commit/ff5a9f18cf42b01d71d3a88fb5d6e42936107592))

- Build the dossier on demand from the symbol page
  ([`fb345aa`](https://github.com/billsioros/stonks/commit/fb345aa28da4b4908a9e53b74a936b6bc5d4612e))

- Compute the business-quality gate
  ([`fefa095`](https://github.com/billsioros/stonks/commit/fefa09590486a509214e5d296ff5f5495a7b295e))

- Cross-check vendor figures against XBRL and verify debt maturities
  ([`6412eec`](https://github.com/billsioros/stonks/commit/6412eecd1d99ae45ec2f68e73ceba77722fc4972))

- Feed primary filing evidence into the deep dive
  ([`05d0666`](https://github.com/billsioros/stonks/commit/05d0666f517dd0b6f689cc066ee936986fe80b54))

- Feed the dossier and its unverified list into the memo
  ([`3e2661d`](https://github.com/billsioros/stonks/commit/3e2661d89ddb77a6e7298032a71fcbfbf96bdb53))

- Make screener columns self-explanatory
  ([`67ee29f`](https://github.com/billsioros/stonks/commit/67ee29f2cf2ba36b53ef1776bf25bdeb15b1fd70))

- Render the deep-dive gate strip and portfolio panel
  ([`e9ac6a8`](https://github.com/billsioros/stonks/commit/e9ac6a8f362ba1b3decf3f49a3e645b75d51cc6d))

- Show honest sync and compatibility badges in the masthead
  ([`8bcf177`](https://github.com/billsioros/stonks/commit/8bcf1778a31a9b57f42b00163eda9028cbe07a03))

- Sweep filings for red flags and check their freshness
  ([`b47f27c`](https://github.com/billsioros/stonks/commit/b47f27c508250edf70d94235892ed9c2132ed032))

### Testing

- Add the dossier gate model
  ([`0809477`](https://github.com/billsioros/stonks/commit/08094776430b6fd9ef4230dd6e44ec39db607b3b))


## v2.5.0 (2026-11-23)

### Bug Fixes

- Drop the active-filter summary and move the column guide below the table
  ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))

- Keep the worker loop alive and contextualise the 13F whale flag
  ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))

- Rate a single model as unrated, warn on malformed sync times, and widen the drift tolerance
  ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))

- **store**: Atomic queries, safe LIMIT/OFFSET parameterization, and StockQueryResult
  ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))

- **store**: Filter validation for unknown columns, empty enum lists, and inverted bounds
  ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))

- **ui**: HTML tag replacement, filter pruning, and sync staleness banner
  ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))

### Features

- Fold the 13F caveat into the column guide ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))

- Send company profiles to the screener report and explain every column
  ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))

- **stockanalysis**: Ingest shares_insiders_percent alongside shares_insiders_pct
  ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))

- **store**: Expand schema with side-by-side metrics and backfill
  ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))

- **valuation**: Add cyclical peak detection and valuation triangulation classification
  ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))

- **worker,sanity**: Persist sync health metadata and guard sanity truncation
  ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))

### Testing

- Seed the screener and detail rows instead of relying on a local database
  ([#3](https://github.com/billsioros/stonks/pull/3),
  [`48cbb5b`](https://github.com/billsioros/stonks/commit/48cbb5bcb70ab891ba10ae0a184382538b3e188f))


## v2.4.0 (2026-11-23)

### Features

- Detail pages, alerts, screener fixes, backtest contributions, and interactive charts
  ([`2ab9220`](https://github.com/billsioros/stonks/commit/2ab92200a28c7fb4737239b1929834753ed65d7d))


## v2.3.0 (2026-05-06)

### Features

- Update app branding with custom favicon, add project backstory to README, and remove unused
  database method
  ([`4434b14`](https://github.com/billsioros/stonks/commit/4434b147965ea4512956066c9d73dd4381fd20d7))


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
