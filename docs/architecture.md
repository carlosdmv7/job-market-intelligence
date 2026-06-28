# Architecture

```
 free public job APIs (Remotive, Arbeitnow, RemoteOK)        [httpx, no key]
            │  jmi_scrapers → canonical JobPosting
            ▼
 Prefect flows (orchestration/jmi_flows)
   ingest  ──────────────►  raw.raw_job_postings   (append-only event log)
   enrich  ── local LLM ──►  raw.raw_job_enrichment (1 row per content_hash)
            │                         (Ollama by default; Gemini/Anthropic optional)
            ▼
 MotherDuck (DuckDB)  —  dbt medallion (dbt/jmi)
   staging.stg_*            cleaning
   staging.int_*            cross-source dedup  (canonical_job_id)
   marts.FT_/DT_*           dimensional model + FT_JOB_SNAPSHOT_DAILY
            │
            ▼
 Streamlit app (app/streamlit_app)
   pages: Visa Sponsorship · Market Trends · Ask the Data (text-to-SQL agent)
```

## Layers & grain

| Layer | Object | Grain |
|---|---|---|
| `raw.raw_job_postings` | `JobPosting` | one **observation** of a source posting at one scrape time (append-only) |
| `raw.raw_job_enrichment` | `JobEnrichment` | one LLM enrichment per **content version** (`content_hash`) |
| `staging.stg_*` | cleaned views | same grain as raw |
| `staging.int_job_postings_deduplicated` | dedup | one **canonical** posting (cross-source) |
| `marts.FT_JOB_POSTING` | fact | one canonical posting (current state) + enrichment |
| `marts.FT_JOB_SNAPSHOT_DAILY` | fact | one source posting per **observed day** |
| `marts.DT_COMPANY / DT_SOURCE / DT_DATE` | dimensions | — |

## Identity & keys

- Per-source identity: `(source, source_job_id)`.
- Content version / change detection / enrichment join key: `content_hash`
  = sha256 of normalized (source, source_job_id, title, company, location,
  salary_raw, description). Computed in `jmi_core` **and** re-derivable in dbt.
- Cross-source cluster: `canonical_job_id` — assigned in dbt `int_`, never in raw.

## Conventions

- Python: Pydantic v2 contracts in `jmi_core` are the single source of truth;
  the DuckDB DDL (`warehouse/ddl/`) mirrors them by hand. Bump `SCHEMA_VERSION`
  on any breaking change to either side.
- raw/staging: lowercase snake_case. marts: `FT_`/`DT_` (the company convention).
- Everything is a uv workspace member; `httpx`/`duckdb`/`structlog` are the only
  heavy core deps. The LLM provider is pluggable (`jmi_enrichment.providers`).

See `adr/` for the decisions behind these.
