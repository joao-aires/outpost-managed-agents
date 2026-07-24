FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    kubectl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app /tmp/uv_cache \
    && chown -R 1000:1000 /app /tmp/uv_cache

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency files
COPY pyproject.toml README.md ./

# Install dependencies
RUN uv sync --frozen --no-dev || uv sync --no-dev

# Copy application code
COPY app/ ./app/

RUN chown -R 1000:1000 /app

# Expose API port
EXPOSE 8000

ENV HOME=/app
ENV UV_CACHE_DIR=/tmp/uv_cache
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8000

USER 1000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
