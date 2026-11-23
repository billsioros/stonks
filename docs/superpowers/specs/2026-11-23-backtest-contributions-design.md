# Backtest Contributions Design

**Date:** 2026-11-23
**Status:** Approved by the user in chat.

## Intent

The user invests monthly into several tickers with fixed sums (for example €600 into VUAA and €400 into NVDA) instead of one lump sum with percentage weights. The backtest should model that in a single run: money arriving on a schedule, split into per-ticker amounts, with shares accumulating. They want rebalancing to be a choice alongside drift.

## Decisions made with the user

- **Two allocation modes.** Percentages work as today. Fixed amounts mean each row is the sum added at every contribution.
- **Recurring contributions.** Cadence of none / monthly / quarterly / semiannual / annual, with a per-contribution amount. Monthly is the default cadence when used. Initial investment may be zero and both may coexist.
- **Rebalance or drift.** "No rebalancing" means drift; any other cadence resets holdings to the target mix implied by the allocation numbers, after that month's contribution has been added.
- **No FX conversion.** Euro amounts are plain currency units; the app's prices and results stay unconverted.
- **Sane defaults.** Percentages, initial 10,000, contribution off, monthly cadence, annual rebalance. Other defaults are the builder's call.

## Engineering consequences

- Cash flows distort the current account-value-derived CAGR, total return, drawdown and calendar-year table. Compute those from a time-weighted growth index so they describe the strategy, not the deposit schedule.
- Add total invested and a money-weighted annualized return for contribution runs.
- Give the benchmark the same cash flows so the comparison stays fair.
- Saved portfolios gain the new fields without breaking older saved JSON.

## Non-goals

- Currency conversion or currency-aware display.
- New rebalancing algorithms or fractional-share/transaction-cost modelling.
- Changing the ten-year month-end adjusted-close data source.
