<h1 align="center">📈 Stonks Screener 💰</h1>

<p align="center"><em>A local-first stock screener dashboard powered by StockAnalysis.com 🔗</em></p>

<p align="center">
    <a href="https://github.com/billsioros/stonks/actions/workflows/ci.yml">
        <img src="https://github.com/billsioros/stonks/actions/workflows/ci.yml/badge.svg" alt="CI" />
    </a>
    <a href="https://github.com/billsioros/stonks/actions/workflows/cd.yml">
        <img src="https://github.com/billsioros/stonks/actions/workflows/cd.yml/badge.svg" alt="CD" />
    </a>
</p>
<br>

> **The Story**: It all started when I found myself constantly hitting refresh on [StockAnalysis.com](https://stockanalysis.com/stocks/screener/), wishing I had a local-first, lightning-fast version of their legendary screener. I wanted the same depth of data, the same "Quality" filters, and the same sleek experience—but without the subscription walls or browser lag. So, I built **Stonks**: a high-performance local screener that mirrors the powerful filters of the web's best tools, powered by a persistent local database and a background worker that keeps the data fresh while I focus on finding the next 10-bagger.

<br>

## :rocket: Features

- 📊 **Dynamic Screener** — Filter, sort, and paginate through thousands of stocks.
- 🎯 **Advanced Filtering** — P/E, ROE, Market Cap, Growth, and 20+ other fundamental metrics.
- 📋 **Smarter Views** — Switch between Valuation, Profitability, Growth, and Financial Health presets.
- 🌟 **One-Click Screens** — Quality Compounders, Dividend Champions, Growth Machines, and more.
- ⭐ **Persistent Watchlist** — Track your favorite symbols across sessions (SQLite backed).
- 💾 **Saved Configurations** — Save your complex filter setups for later use.
- 🔍 **Symbol Detail Pages** — Click any screener or watchlist row for an in-app page with Overview, Financials (annual and quarterly statements), Statistics, Metrics, and Forecast, fetched live from StockAnalysis and cached per symbol.
- 🔔 **Watchlist Alerts** — The worker flags watched symbols that get cheap, drop or jump sharply, or hit the news, and the app shows them in a banner plus a badge on the Watchlist tab.
- 📥 **Export Ready** — Download your results or watchlist to CSV.

## 🛠️ Getting Started

### Prerequisites

- [Docker](https://www.docker.com/) & [Docker Compose](https://docs.docker.com/compose/)
- No API key required — data comes from StockAnalysis.com

### Running with Docker

1. **Build and start the services**:

   ```shell
   docker compose up -d --build
   ```

2. **Access the Dashboard**:
   Open [http://localhost:8501](http://localhost:8501) in your browser.

## 💻 Local Development

### Installation

We use [uv](https://docs.astral.sh/uv/) for lightning-fast dependency management:

```bash
uv sync --all-groups
```

### Running the App

```bash
uv run poe app
```

### Running Tests

```bash
uv run poe test      # Run full suite
uv run poe coverage  # Run with coverage report
```

## 🏗️ Architecture

```
src/stonks/
├── app.py          # Dashboard UI (Streamlit)
├── config.py       # Settings and column definitions
├── presets.py      # One-click screens
├── store.py        # SQLite persistence, filtering, sorting
├── stockanalysis.py # Bulk screener data provider
└── worker.py       # Background sync service
```

## 📄 License

This project is licensed under the MIT License.
