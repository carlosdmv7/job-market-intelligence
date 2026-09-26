# Architecture

```
 6 operational sources, all via jmi_scrapers:
   Remotive, Arbeitnow, RemoteOK  (remote-first boards)      [httpx, no key]
   JobTech (Platsbanken, SE)                                 [httpx, no key]
   Adzuna per-country (NL/DE/ES — the relocation corpora)    [httpx, free key]
   Employers' Greenhouse/Ashby boards (IE — 33 employers,
     a sample of employers, not the market)                  [httpx, no key]
   (honeypot is registered but unverified — not counted, not run)
            │  jmi_scrapers → canonical JobPosting
            ▼
 Prefect flow jmi-daily (orchestration/jmi_flows/daily.py): one task per source,
 enrich, dbt build, record. Deployed to Prefect Cloud (schedule + history), served
 for one pass by an hourly GitHub Actions job (gha_runner.py) — free tier, no pool
   ingest  ──────────────►  raw.raw_job_postings   (append-only event log)
   enrich  ──── LLM ─────►  raw.raw_job_enrichment (1 row per content_hash)
            │        (Gemini free tier: 20 requests/day/model x 10 postings per
            │         request = ~200/day; queue is data roles only, freshest first)
            ▼
 IND recognised-sponsor register (~12.8k employers) ─► dbt seed
            │
 MotherDuck (DuckDB)  —  dbt medallion (dbt/jmi)
   staging.stg_*            cleaning + normalized sponsor register
   staging.int_*            cross-source dedup  (canonical_job_id)
   marts.FT_/DT_*           dimensional model + FT_JOB_SNAPSHOT_DAILY
                            + is_target_role (data role?) and is_active (still
                              on the board?) + is_recognised_sponsor/sponsor_kvk
            │
            ▼
 Streamlit app (app/streamlit_app), top nav, entry point Home.py
   Overview · Find Jobs · My Fit (CV stack overlap, evidence-weighted) · Market Trends ·
   Market Detail (one market, incl. the NL sponsor register) ·
   Ask the Data (text-to-SQL agent) · How It Works
            │
            ▼
 Run history ─► meta.pipeline_run (appended by the pipeline, read by the app's
                freshness strip — never a committed status file)
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
  heavy core deps. The LLM provider is pluggable (`jmi_enrichment.providers`),
  defaulting to Gemini's free tier — the only one that runs on a laptop, a
  GitHub runner and Streamlit Community Cloud alike (ADR 0008).
- "Is this a data role?" has exactly one definition, `jmi_core.roles`, shared by
  the scrapers, the enrichment queue and dbt (via the `jmi_is_target_role`
  macro); `scrapers/tests/test_target_role_parity.py` keeps the two in step.
- Sources differ in *depth*, not just coverage: Adzuna publishes a ~500-char
  teaser, JobTech the full ~4,000-char ad, so extraction quality is a property
  of the source and not of the market. Anything aggregated per country carries
  that caveat (ADR 0011). `staging.stg_job_postings` is at observation grain —
  join it to the marts on `content_hash` and a posting fans out once per
  sighting.

See `adr/` for the decisions behind these.
