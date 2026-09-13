-- Medallion schemas for the Job Market Intelligence warehouse (MotherDuck/DuckDB).
-- `raw`     : append-only, as-scraped event log + LLM enrichment (owned by ingestion).
-- `staging` : dbt stg_/int_ models (cleaning, parsed salary, cross-source dedup).
-- `marts`   : dbt FT_/DT_ dimensional models + FT_JOB_SNAPSHOT_DAILY.
-- `meta`    : how the pipeline itself ran (owned by the flows, not by dbt).
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS meta;
