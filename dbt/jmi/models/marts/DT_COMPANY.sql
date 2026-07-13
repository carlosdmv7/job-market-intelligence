-- Company dimension. Grain: company_name + country (same name across countries
-- stays distinct, matching the FK FT_JOB_POSTING builds).

with postings as (
    select * from {{ ref('int_job_postings_deduplicated') }}
    where company_name is not null
),

sponsors as (
    select * from {{ ref('stg_recognised_sponsors') }}
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
    {{ dbt_utils.generate_surrogate_key(['a.company_name', 'a.country_code']) }} as company_key,
    a.company_name,
    a.country_code,
    a.posting_count,
    a.first_posting_at,
    a.last_seen_at,
    -- IND recognised sponsor cross-reference (deterministic, no LLM)
    (s.company_norm is not null)     as is_recognised_sponsor,
    s.kvk_number                     as sponsor_kvk
from agg a
left join sponsors s
    on {{ jmi_normalize_company('a.company_name') }} = s.company_norm
