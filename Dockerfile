FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies (use system python for simplicity in container)
RUN uv sync --frozen --no-dev

# Copy source code
COPY src ./src
COPY README.md ./

# Create data directory
RUN mkdir -p data/cache

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV FINNHUB_API_KEY=""

# Default command (can be overridden in docker-compose)
CMD ["uv", "run", "streamlit", "run", "src/stonks/app.py"]
