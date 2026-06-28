-- Cross-source deduplication (the dedup ADR's home).
--   1. collapse the event log to the latest observation per source posting
--   2. assign a deterministic canonical_job_id (company + title + country)
--   3. pick one representative row per canonical cluster
-- The embedding-based edge-case pass (near-duplicate titles) plugs in here in
-- Phase 2; today it is purely the deterministic hash.

with postings as (
    select * from {{ ref('stg_job_postings') }}
),

latest_per_source_posting as (
    select *
    from (
        select
            *,
            row_number() over (
                partition by source, source_job_id
                order by scraped_at desc
            ) as _rn
        from postings
    )
    where _rn = 1
),

keyed as (
    select
        *,
        {{ jmi_canonical_key('company_name', 'title', 'country_code') }} as canonical_job_id
    from latest_per_source_posting
),

clustered as (
    select
        *,
        count(*)      over (partition by canonical_job_id) as cluster_size,
        row_number()  over (
            partition by canonical_job_id
            order by posted_at asc nulls last, scraped_at desc
        ) as _cluster_rn
    from keyed
)

select
    canonical_job_id,
    cluster_size,
    content_hash,
    source,
    source_job_id,
    source_url,
    apply_url,
    title,
    company_name,
    description_raw,
    detected_language,
    location_raw,
    country_code,
    is_remote_raw,
    posted_at,
    valid_through,
    salary_raw,
    employment_type_raw,
    seniority_raw,
    scraped_at,
    scraped_date
from clustered
where _cluster_rn = 1
