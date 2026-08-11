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

## Alternatives considered

- **Dedup at ingestion, before writing raw.** One less transformation and a
  smaller warehouse. Rejected because it makes raw lossy: the clustering recipe
  is the part most likely to change, and a bad heuristic would have already
  discarded the evidence needed to fix it. Raw stays an event log precisely so
  dedup can be re-run.
- **Embedding similarity from day one.** Better on near-duplicates ("Sr. Data
  Engineer" vs "Senior Data Engineer (m/f/d)"). Rejected as the *first* pass: it
  costs an embedding call per posting against a 0€ budget, and it is
  unfalsifiable without the deterministic baseline to compare against. The `int_`
  layer is where it plugs in when there is a reason.
- **One shared normalization implementation instead of two.** Calling the Python
  recipe from dbt (or vice versa) removes the documented drift risk. Rejected:
  it would mean a Python UDF inside the warehouse or a pre-materialized key
  table, both of which trade a small, tested duplication for real operational
  coupling.
