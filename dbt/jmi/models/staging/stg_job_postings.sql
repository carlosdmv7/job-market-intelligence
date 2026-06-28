-- Cleaned pass over raw posting observations. One row per observation; the
-- append-only event log is preserved (dedup happens in the int_ layer).

with source as (
    select * from {{ source('raw', 'raw_job_postings') }}
)

select
    content_hash,
    source,
    source_job_id,
    source_url,
    apply_url,
    scraped_at,
    cast(scraped_at as date)                      as scraped_date,
    title,
    nullif(trim(company_name), '')                as company_name,
    company_url,
    description_raw,
    detected_language,
    location_raw,
    upper(nullif(trim(country_code), ''))         as country_code,
    is_remote_raw,
    posted_at,
    valid_through,
    salary_raw,
    employment_type_raw,
    seniority_raw,
    ingestion_run_id,
    schema_version,
    _loaded_at
from source
