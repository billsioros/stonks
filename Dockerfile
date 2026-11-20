FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies only (cache this layer)
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code and the Streamlit theme
COPY src ./src
COPY .streamlit ./.streamlit
COPY README.md ./

# Install the project itself
RUN uv sync --frozen --no-dev

# Create data directory
RUN mkdir -p data/cache

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV PATH="/app/.venv/bin:$PATH"

# Default command
CMD ["streamlit", "run", "src/stonks/app.py"]
