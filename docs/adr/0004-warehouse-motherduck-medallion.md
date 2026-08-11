# ADR 0004 — MotherDuck (DuckDB) warehouse with a dbt medallion

**Status:** accepted

## Context
Need a warehouse that is free at this scale, SQL-first, plays well with dbt and
Python, and that a single developer can run end to end.

## Decision
MotherDuck (managed DuckDB) on the free tier. Schemas `raw` / `staging` /
`marts`. raw tables are created by hand-written DDL (`warehouse/ddl/`) owned by
the ingestion side (mirrors the Pydantic contracts); dbt (`dbt-duckdb`) owns
`staging` → `marts`. A `generate_schema_name` override makes models land in
exactly `staging`/`marts` (not `<target>_staging`). dbt's `ci` target points at
a local DuckDB file so `dbt build`/`parse` run with no cloud creds.

## Consequences
- Same engine locally (file) and in the cloud (MotherDuck) — trivial CI.
- DuckDB token must be passed to the process env (handled in `jmi_core.warehouse`).
- DDL is mirrored by hand; `SCHEMA_VERSION` + tests guard drift.

## Alternatives considered

- **BigQuery / Snowflake.** The default answers for "analytics warehouse", both
  with usable free allowances. Rejected against the 0€ constraint of
  [ADR 0005](0005-zero-cost-stack.md): both meter storage or compute in ways
  that make a daily pipeline a bill sooner or later, and neither gives the same
  engine locally, so CI would need either credentials or a second dialect.
- **Postgres (Supabase/Neon free tier).** Genuinely free and familiar.
  Rejected: row-store performance on the analytical scans this app runs is the
  wrong shape, and `dbt-postgres` would diverge from the DuckDB used locally.
- **Plain DuckDB files in object storage, no MotherDuck.** Removes the last
  hosted dependency. Rejected because the Streamlit app needs concurrent
  read access to a warehouse that a scheduled job is writing, which is exactly
  what a file in a bucket does not give you.
- **Skipping the medallion (raw straight to marts).** Fewer models to maintain
  at this size. Rejected: the dedup grain needs somewhere to live, and the
  staging layer is where the raw-vs-modelled boundary stays testable.
