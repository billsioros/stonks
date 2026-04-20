<h1 align="center">📈 Stonks Screener 💰</h1>

<p align="center"><em>A powerful, modular stock screener REST API & Dashboard powered by Finnhub 🔗</em></p>

<p align="center">
    <a href="https://github.com/billsioros/stonks/actions/workflows/ci.yml">
        <img src="https://github.com/billsioros/stonks/actions/workflows/ci.yml/badge.svg" alt="CI" />
    </a>
    <a href="https://github.com/billsioros/stonks/actions/workflows/cd.yml">
        <img src="https://github.com/billsioros/stonks/actions/workflows/cd.yml/badge.svg" alt="CD" />
    </a>
</p>

## :rocket: Features

- 📊 **Dynamic Screener** — Filter, sort, and paginate through thousands of stocks.
- 🎯 **Advanced Filtering** — P/E, ROE, Market Cap, Growth, and 20+ other fundamental metrics.
- 📋 **Smarter Views** — Switch between Valuation, Profitability, Growth, and Financial Health presets.
- 🌟 **One-Click Screens** — Quality Compounders, Dividend Champions, Growth Machines, and more.
- ⭐ **Persistent Watchlist** — Track your favorite symbols across sessions (SQLite backed).
- 💾 **Saved Configurations** — Save your complex filter setups for later use.
- 📥 **Export Ready** — Download your results or watchlist to CSV.

## 🛠️ Getting Started

### Prerequisites

- [Docker](https://www.docker.com/) & [Docker Compose](https://docs.docker.com/compose/)
- [Finnhub API Key](https://finnhub.io/) (Free tier works great)

### Running with Docker

1. **Create a `.env` file** in the root directory:

    ```env
    FINNHUB_API_KEY='your_api_key_here'
    ```

2. **Build and start the services**:

   ```shell
   docker compose up -d --build
   ```

3. **Access the Dashboard**:
   Open [http://localhost:8501](http://localhost:8501) in your browser.

## 💻 Local Development

### Installation

We use [uv](https://docs.astral.sh/uv/) for lightning-fast dependency management:

```bash
uv sync --all-groups
```

### Running the App

```bash
export FINNHUB_API_KEY="your_key"
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
├── engine.py       # Filtering/Sorting Logic
├── metrics.py      # Finnhub API Client & Normalizers
├── universe.py     # Stock Universe Management
├── cache.py        # SQLite-based KV Cache
├── store.py        # Persistence (Screens, Watchlist)
└── worker.py       # Background Sync Service
```

## 📄 License

This project is licensed under the MIT License.
