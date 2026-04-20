# Stonks — Streamlit Stock Screener

A powerful stock screener built with Streamlit, powered by [Finnhub](https://finnhub.io) free-tier API.

## Features

- 📊 **Screener Table** — Sort, paginate, search across ~30 fundamental metrics
- 🎯 **Filter Builder** — Numeric thresholds (min/max) + enum filters (exchange, type, currency)
- 📋 **Column Presets** — Overview, Valuation, Profitability, Growth, Financial Health views
- 🌟 **Popular Screens** — 8 predefined screens (Quality Compounders, Dividend Champions, etc.)
- 💾 **Saved Screens** — Save and load your custom filter configurations
- ⭐ **Watchlist** — Track symbols across sessions (SQLite-persisted)
- 📥 **CSV Download** — Export filtered results or your watchlist

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- [Finnhub API key](https://finnhub.io/) (free tier)

### Install

```bash
uv sync
```

### Run

```bash
# Set your API key
export FINNHUB_API_KEY="your_key_here"

# Launch the app
uv run poe app
# or
uv run streamlit run src/stonks/app.py
```

## Architecture

```
src/stonks/
├── app.py          # Streamlit entry point
├── universe.py     # Symbol list loader (Finnhub stock_symbols)
├── metrics.py      # Fundamental metrics fetcher (Finnhub basic_financials)
├── cache.py        # Disk-based JSON cache with TTL
├── store.py        # SQLite persistence (saved screens, watchlist)
├── engine.py       # Filter/sort/paginate engine
├── presets.py      # Predefined popular screens
└── config.py       # Configuration constants
```

## Metrics Available

| Category | Metrics |
|----------|---------|
| **Valuation** | P/E, P/B, P/S, PEG, EV/EBITDA |
| **Profitability** | Gross Margin, Operating Margin, Net Margin, ROA, ROE, ROIC |
| **Growth** | Revenue Growth 3Y/5Y, EPS Growth 3Y/5Y |
| **Financial Health** | Current Ratio, D/E, LT D/E, FCF Margin, FCF/Share |
| **Other** | Market Cap, Dividend Yield, Beta, 52W High/Low, Price |

## Development

```bash
# Run tests
uv run poe test

# Type checking
uv run poe lint
```

## License

MIT
