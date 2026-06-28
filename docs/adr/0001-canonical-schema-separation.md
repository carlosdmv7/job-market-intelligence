# ADR 0001 — Separate raw and enriched contracts (composed models + tables)

**Status:** accepted

## Context
A posting has scraped fields (immutable, as-posted) and LLM-derived fields
(re-runnable, model/prompt-dependent). Mixing them invites full-row rewrites on
re-enrichment and blurs provenance.

## Decision
Two Pydantic models in `jmi_core`: `JobPosting` (raw, required at scrape) and
`JobEnrichment` (LLM output + lineage), landing in two tables
(`raw.raw_job_postings`, `raw.raw_job_enrichment`) joined on `content_hash`.
Raw is an append-only event log; enrichment is keyed by content version so each
distinct content is enriched once and re-enriched only when content (or
prompt/model) changes.

## Consequences
- Enrichment reruns never touch raw; raw stays replayable.
- The daily snapshot fact falls out of the append-only raw log for free.
- Two write paths instead of one (acceptable; loaders live in `jmi_core.warehouse`).
