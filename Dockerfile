FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install deps first (cached layer when only source changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Install project package
COPY src/ ./src/
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

ENV STORAGE_PATH=/storage/data \
    DB_PATH=/storage/meta/metadata.db \
    HOST=0.0.0.0 \
    PORT=9000 \
    LOG_LEVEL=info \
    ZSTD_LEVEL=3

# Pre-create dirs so the volume is initialised with the right structure
RUN mkdir -p /storage/data /storage/meta

VOLUME ["/storage"]

EXPOSE 9000

CMD ["fastapi", "run", "src/main.py", "--host", "0.0.0.0", "--port", "9000"]
