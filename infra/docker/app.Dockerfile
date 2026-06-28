# Streamlit app image. Built from the repo root (context: ..).
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY . /app

# Install the app package and its workspace deps (jmi-core, jmi-enrichment).
RUN uv sync --package jmi-app --no-dev

EXPOSE 8501

CMD ["uv", "run", "streamlit", "run", "app/streamlit_app/Home.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
