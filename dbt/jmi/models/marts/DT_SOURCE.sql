-- Source dimension with static metadata about each scraped platform.

with sources as (
    select distinct source from {{ ref('int_job_postings_deduplicated') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['source']) }} as source_key,
    source,
    case source
        when 'jobtech'      then 'SE'  -- Platsbanken, Sweden's public employment service
        when 'honeypot'     then 'NL'
        when 'infojobs'     then 'ES'
        when 'stepstone'    then 'DE'
        when 'irishjobs'    then 'IE'
        when 'itjobs'       then 'PT'
        else null            -- remotive/remoteok/arbeitnow/adzuna/techmeabroad: multi-country
    end as primary_country,
    case
        when source in ('linkedin', 'indeed', 'remotive', 'remoteok', 'adzuna') then 'aggregator'
        else 'job_board'
    end as source_type,
    case
        when source in ('remotive', 'remoteok') then true
        else false
    end as is_remote_first
from sources
