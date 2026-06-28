# ADR 0002 — Cross-source deduplication runs in dbt (int_ layer)

**Status:** accepted

## Context
The same role appears on multiple sources. We need one canonical posting for
analytics, but dedup logic will evolve (deterministic key today, embeddings for
edge cases later) and must stay revisable without rewriting history.

## Decision
A cheap deterministic `content_hash` is computed at ingestion (change detection
+ enrichment key). Cross-source clustering happens in
`staging.int_job_postings_deduplicated`: collapse to the latest observation per
source posting, assign `canonical_job_id` = hash of normalized
(company + title + country), pick one representative per cluster. The same
normalization recipe exists in Python (`jmi_enrichment.dedup.canonical_key`) and
in a dbt macro (`jmi_canonical_key`). `canonical_job_id` never appears in raw.

## Consequences
- Raw stays immutable; dedup is a re-runnable transformation.
- Embedding-based near-duplicate matching plugs into `int_` in Phase 2.
- Two implementations of the normalization recipe to keep in sync (documented).
