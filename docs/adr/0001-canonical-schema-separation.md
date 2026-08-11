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

## Alternatives considered

- **One wide table with nullable LLM columns.** Simplest to query and one write
  path instead of two. Rejected because every re-enrichment becomes a full-row
  rewrite over immutable scraped data, and "never enriched" stops being
  distinguishable from "enriched and found nothing" — the exact distinction the
  visa feature depends on.
- **Enrichment as a JSON blob on the raw row.** Keeps one table and stays
  schema-flexible. Rejected: the fields are queried constantly (visa status,
  role family, languages), so they would be unpacked in every model, and
  Pydantic validation of the LLM output would have nothing to validate against.
- **Key enrichment by `source_job_id` instead of `content_hash`.** Cheaper to
  reason about, but a re-posted ad with edited text would keep a stale
  classification. `content_hash` makes "the text changed" and "re-enrich this"
  the same event.
