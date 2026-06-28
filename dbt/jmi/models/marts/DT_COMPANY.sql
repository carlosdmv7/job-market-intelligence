-- Company dimension. Grain: company_name + country (same name across countries
-- stays distinct, matching the FK FT_JOB_POSTING builds).

with postings as (
    select * from {{ ref('int_job_postings_deduplicated') }}
    where company_name is not null
),

agg as (
    select
        company_name,
        country_code,
        count(*)                     as posting_count,
        min(posted_at)               as first_posting_at,
        max(scraped_at)              as last_seen_at
    from postings
    group by 1, 2
)

select
    {{ dbt_utils.generate_surrogate_key(['company_name', 'country_code']) }} as company_key,
    company_name,
    country_code,
    posting_count,
    first_posting_at,
    last_seen_at
from agg
