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
