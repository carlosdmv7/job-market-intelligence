# Prefect worker image (runs the ingest/enrich flows on your work pool).
# Built from the repo root (context: ..).
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY . /app

RUN uv sync --package jmi-flows --no-dev

# Start a worker against your centralized Prefect server's pool.
# Requires PREFECT_API_URL (and auth) in the environment.
CMD ["uv", "run", "prefect", "worker", "start", "--pool", "jmi-pool"]
