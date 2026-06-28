# Job Market Intelligence Engine

An end-to-end **data-engineering + analytics-engineering + LLM** project that
scrapes EU tech jobs, enriches them with a language model, models them
dimensionally, and serves the result through an analytical app — including a
natural-language **"Ask the Data"** agent.

**Killer feature:** detect postings with **visa sponsorship** aimed at profiles
that need to relocate (built for a Spanish data professional eyeing the
Netherlands / EU), with an auditable confidence + evidence for every flag.

> **Runs at 0€.** MotherDuck free tier + a **local LLM via Ollama** + free,
> no-registration public job APIs. No paid services required. (Cloud LLMs and
> anti-bot scraping are optional, behind one env var — see
> [ADR 0005](docs/adr/0005-zero-cost-stack.md).)

---

## What's inside

```
free public APIs ──httpx──► Prefect ingest ─► raw.raw_job_postings  (append-only)
                                   │
                       Prefect enrich (local LLM) ─► raw.raw_job_enrichment
                                   │
              MotherDuck + dbt medallion: stg_ → int_ (dedup) → FT_/DT_ marts
                                   │
                 Streamlit: Visa Sponsorship · Trends · Ask the Data (text-to-SQL)
```

Full diagram and grain table: [docs/architecture.md](docs/architecture.md).

## Repo layout (uv workspace monorepo)

| Path | What |
|---|---|
| [libs/jmi_core](libs/jmi_core) | Canonical Pydantic contracts, settings, logging, MotherDuck client |
| [scrapers](scrapers) | `httpx` scrapers for free APIs (Remotive/Arbeitnow/RemoteOK) + JSON-LD helper |
| [enrichment](enrichment) | Pluggable LLM providers (Ollama/Gemini/Anthropic), salary parser, dedup |
| [orchestration](orchestration) | Prefect ingest + enrich flows, `prefect.yaml` |
| [warehouse/ddl](warehouse/ddl) | DuckDB DDL for the `raw` schema (mirrors the models) |
| [dbt/jmi](dbt/jmi) | Medallion project: staging → int dedup → `FT_`/`DT_` marts |
| [app](app) | Streamlit app + controlled text-to-SQL agent |
| [infra](infra) | Docker Compose (Ollama + app), Dockerfiles |
| [docs](docs) | Architecture + ADRs |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python 3.11)
- [Ollama](https://ollama.com) for the local LLM
- A free [MotherDuck](https://motherduck.com) account + a database (e.g. `job-market-intelligence`)

## Quickstart

```bash
# 1. configure
cp .env.example .env          # set motherduck_token and JMI_DUCKDB_DATABASE
uv sync --all-packages        # install every workspace member + dev tools

# 2. local LLM (0€)
make ollama-pull              # pulls qwen2.5:7b (override with MODEL=gemma3)

# 3. build the warehouse + run the pipeline
make warehouse-init           # creates raw/staging/marts in MotherDuck
make ingest-all               # remotive + arbeitnow + remoteok -> raw
make enrich                   # local LLM classification -> raw
make dbt-build                # staging -> marts

# 4. explore
make app                      # Streamlit at http://localhost:8501
```

Or bring up Ollama + the app with Docker: see [infra/README.md](infra/README.md).

## Choosing the LLM

Default is local Ollama (no key, no cost). To switch, set in `.env`:

```bash
# Gemini free tier (use a 2.5 model — 2.0-flash has no free tier on some accounts)
JMI_LLM_PROVIDER=gemini ; JMI_LLM_MODEL=gemini-2.5-flash ; GEMINI_API_KEY=...
# Anthropic (paid)
JMI_LLM_PROVIDER=anthropic ; JMI_LLM_MODEL=claude-haiku-4-5 ; ANTHROPIC_API_KEY=...
```

The enrichment classifier and the text-to-SQL agent both use this one setting.

## Development

```bash
make check        # ruff + mypy + pytest
make test         # pytest only
make fmt          # auto-format
```

**Status:** the offline-testable spine is green — **59 unit tests pass**
(`jmi_core`, scrapers, enrichment incl. provider wiring, Prefect pipeline, the
text-to-SQL guard), and the **dbt medallion builds clean on DuckDB (42 models +
data tests)** including cross-source dedup and `FT_JOB_SNAPSHOT_DAILY`. CI
(`.github/workflows/ci.yml`) runs lint + type-check + tests and `dbt parse`.

## Key decisions (ADRs)

1. [Separate raw / enriched contracts](docs/adr/0001-canonical-schema-separation.md)
2. [Cross-source dedup in dbt](docs/adr/0002-cross-source-dedup-in-dbt.md)
3. [Visa as enum + confidence + evidence](docs/adr/0003-visa-enum-classification.md)
4. [MotherDuck + dbt medallion](docs/adr/0004-warehouse-motherduck-medallion.md)
5. [Zero-cost stack: local LLM + free APIs](docs/adr/0005-zero-cost-stack.md)

## Roadmap

- **Now (0€):** free-API ingestion, local-LLM enrichment, medallion marts, app + agent.
- **Phase 2:** embedding-based near-duplicate dedup; deterministic salary parser into staging.
- **Improvement section:** Adzuna (per-country NL/ES/DE), Scrapfly for LinkedIn/Indeed,
  Prefect Cloud deployments, app on Streamlit Community Cloud.

## Tech stack

Python 3.11 · Pydantic v2 · DuckDB/MotherDuck · dbt · Prefect · httpx · Ollama ·
Streamlit · uv · ruff · mypy · pytest · GitHub Actions.
