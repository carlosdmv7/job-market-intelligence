-- meta.pipeline_run — one row per daily pipeline execution.
--
-- Grain: one pipeline run. Append-only, like raw: a run is an event that
-- happened, not a record to be corrected.
--
-- Why a table and not a committed JSON file: the app's freshness header needs
-- "how many dbt tests passed", and the only other way to get that number to a
-- deployed app was to commit it to the repo on every run — which buried the
-- human git history under two bot commits a day. Here the same history is
-- queryable instead of being reconstructed from `git log` of a JSON blob.
--
-- Written by jmi_flows.dbt_status at the end of every run, including failed
-- ones: a log that only records successes cannot tell you the pipeline stopped.

CREATE TABLE IF NOT EXISTS meta.pipeline_run (
    run_id            VARCHAR       NOT NULL,  -- GitHub Actions run id, or "local"
    run_started_at    TIMESTAMPTZ,             -- dbt's own generated_at
    recorded_at       TIMESTAMPTZ   NOT NULL,  -- when this row was written
    conclusion        VARCHAR       NOT NULL,  -- success|failure|cancelled|unknown
    dbt_version       VARCHAR,
    tests_total       INTEGER,
    tests_passed      INTEGER,
    models_total      INTEGER,
    models_passed     INTEGER,
    elapsed_seconds   DOUBLE,
    rows_in_warehouse BIGINT,                  -- marts.FT_JOB_POSTING at the end of the run
    last_ingest_at    TIMESTAMPTZ              -- newest last_seen_at in the marts
);
