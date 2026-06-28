-- raw.raw_job_postings — mirrors jmi_core.schema.raw.JobPosting
--
-- Grain: one observation of one source's posting at one scrape time.
-- Append-only: the same logical posting (source, source_job_id) yields one row
-- per daily scrape. content_hash detects when its content actually changed.
--
-- No PRIMARY KEY: this is an immutable event log; uniqueness/dedup is resolved
-- downstream (dbt). Enum-typed columns are stored as VARCHAR — Pydantic owns
-- validation; the warehouse stays portable and dbt-friendly. Allowed values are
-- noted in comments next to each such column.

CREATE TABLE IF NOT EXISTS raw.raw_job_postings (
    -- identity & provenance
    source              VARCHAR       NOT NULL,  -- linkedin|indeed|honeypot|techmeabroad|infojobs|stepstone|irishjobs|itjobs
    source_job_id       VARCHAR       NOT NULL,
    source_url          VARCHAR       NOT NULL,
    apply_url           VARCHAR,
    ingestion_run_id    VARCHAR,                 -- Prefect flow run id
    scraped_at          TIMESTAMPTZ   NOT NULL,

    -- content (as posted)
    title               VARCHAR       NOT NULL,
    company_name        VARCHAR,
    company_url         VARCHAR,
    description_raw     VARCHAR,
    detected_language   VARCHAR,                 -- ISO 639-1

    -- location
    location_raw        VARCHAR,
    country_code        VARCHAR,                 -- ISO 3166-1 alpha-2
    is_remote_raw       BOOLEAN,

    -- dates
    posted_at           TIMESTAMPTZ,
    valid_through       TIMESTAMPTZ,

    -- as-posted descriptors (normalized versions live in raw_job_enrichment)
    salary_raw          VARCHAR,
    employment_type_raw VARCHAR,
    seniority_raw       VARCHAR,

    -- full source payload for replayability
    raw_payload         JSON,

    -- computed identity & meta
    content_hash        VARCHAR       NOT NULL,  -- = compute_content_hash(...), enrichment join key
    schema_version      VARCHAR       NOT NULL,

    -- warehouse-side bookkeeping
    _loaded_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- Common access paths: logical key, change detection, snapshot windows.
CREATE INDEX IF NOT EXISTS idx_rjp_source_jobid ON raw.raw_job_postings (source, source_job_id);
CREATE INDEX IF NOT EXISTS idx_rjp_content_hash ON raw.raw_job_postings (content_hash);
CREATE INDEX IF NOT EXISTS idx_rjp_scraped_at   ON raw.raw_job_postings (scraped_at);
