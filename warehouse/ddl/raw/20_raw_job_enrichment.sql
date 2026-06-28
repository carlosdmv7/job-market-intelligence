-- raw.raw_job_enrichment — mirrors jmi_core.schema.enrichment.JobEnrichment
--
-- Grain: one LLM enrichment per content version (content_hash). Enrich each
-- distinct content once regardless of how many daily snapshots observe it.
-- content_hash is the PRIMARY KEY so re-runs upsert cleanly (DELETE+INSERT or
-- INSERT OR REPLACE) when content/prompt/model changes.
--
-- The nested VisaSponsorship value object is flattened into visa_* columns.
-- list[str] fields use DuckDB native arrays (VARCHAR[]).

CREATE TABLE IF NOT EXISTS raw.raw_job_enrichment (
    -- keys & lineage
    content_hash            VARCHAR       NOT NULL,
    source                  VARCHAR       NOT NULL,
    source_job_id           VARCHAR       NOT NULL,
    enriched_at             TIMESTAMPTZ   NOT NULL,
    model                   VARCHAR       NOT NULL,  -- e.g. claude-haiku-4-5-20251001
    prompt_version          VARCHAR       NOT NULL,
    schema_version          VARCHAR       NOT NULL,

    -- cost / observability
    input_tokens            BIGINT,
    output_tokens           BIGINT,
    cost_usd                DOUBLE,

    -- normalized classifications
    normalized_role         VARCHAR,
    role_family             VARCHAR,
    seniority               VARCHAR,                 -- intern|junior|mid|senior|lead|principal|manager|unknown
    employment_type         VARCHAR,                 -- full_time|part_time|contract|freelance|internship|temporary|unknown
    remote_policy           VARCHAR,                 -- onsite|hybrid|remote|remote_country_restricted|unknown
    technologies            VARCHAR[],

    -- killer feature: visa + relocation fit (VisaSponsorship flattened)
    visa_status             VARCHAR       NOT NULL,  -- explicit_yes|likely_yes|unclear|likely_no|explicit_no
    visa_confidence         DOUBLE        NOT NULL,  -- 0..1
    visa_evidence           VARCHAR,
    visa_reasoning          VARCHAR,
    requires_local_language BOOLEAN,
    working_languages       VARCHAR[],               -- ISO 639-1
    english_sufficient      BOOLEAN,
    relocation_support      BOOLEAN,

    -- quality / audit
    enrichment_confidence   DOUBLE,                  -- 0..1
    raw_response            JSON,

    -- warehouse-side bookkeeping
    _loaded_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),

    PRIMARY KEY (content_hash)
);

CREATE INDEX IF NOT EXISTS idx_rje_source_jobid ON raw.raw_job_enrichment (source, source_job_id);
CREATE INDEX IF NOT EXISTS idx_rje_visa_status  ON raw.raw_job_enrichment (visa_status);
