.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help install fmt lint type test check ollama-pull ollama-up ollama-down ollama-status warehouse-init ingest ingest-all ingest-nl enrich sponsors-refresh dbt-deps dbt-build app clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Create the venv and install all workspace members + dev tools
	uv sync --all-packages

fmt: ## Auto-format
	uv run ruff format .
	uv run ruff check --fix .

lint: ## Lint (no changes)
	uv run ruff check .
	uv run ruff format --check .

type: ## Type-check
	uv run mypy libs scrapers enrichment orchestration

test: ## Run the test suite
	uv run pytest

check: lint type test ## Lint + type-check + test (run before pushing)

ollama-pull: ## Pull the local LLM (set MODEL to override)
	ollama pull $(or $(MODEL),qwen2.5:7b)

ollama-up: ## Start the Ollama service (only while you need the local LLM)
	sudo systemctl start ollama

ollama-down: ## Unload the model from RAM and stop the Ollama service
	-ollama stop $(or $(MODEL),qwen2.5:7b)
	-sudo systemctl stop ollama

ollama-status: ## Show service state, model loaded in RAM, and free memory
	@echo -n "service: "; systemctl is-active ollama
	@ollama ps 2>/dev/null || echo "(service down — nothing loaded)"
	@free -h | awk 'NR<=2'

warehouse-init: ## Create raw/staging/marts schemas + raw tables in MotherDuck
	uv run python -m jmi_flows.warehouse_init

ingest: ## Run the ingestion flow for one source (SOURCE=remotive)
	uv run python -m jmi_flows.ingest --source $(or $(SOURCE),remotive)

ingest-all: ## Ingest every free no-key source
	@for s in remotive arbeitnow remoteok; do uv run python -m jmi_flows.ingest --source $$s; done

ingest-nl: ## Ingest local NL jobs via Adzuna (needs ADZUNA_APP_ID/KEY) — the relocation corpus
	uv run python -m jmi_flows.ingest --source adzuna

enrich: ## Run the LLM enrichment flow
	uv run python -m jmi_flows.enrich

sponsors-refresh: ## Refresh the IND recognised-sponsor dbt seed (updated monthly)
	uv run python -m jmi_scrapers.ind_sponsors

dbt-deps: ## Install dbt package dependencies (dbt_utils)
	cd dbt/jmi && uv run dbt deps

dbt-build: dbt-deps ## Run dbt staging -> marts
	set -a; [ -f .env ] && . ./.env; set +a; cd dbt/jmi && uv run dbt build

app: ## Launch the Streamlit app
	uv run streamlit run app/streamlit_app/Home.py

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage* **/*.egg-info build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
