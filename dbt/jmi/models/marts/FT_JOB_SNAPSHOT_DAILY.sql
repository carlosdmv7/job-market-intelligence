-- Daily snapshot fact: one row per source posting per day it was observed.
-- This is what the append-only raw event log buys us — postings appearing /
-- disappearing over time, time-to-fill, and trend lines.
--
-- Materialized as a full table, per the marts default in dbt_project.yml. At
-- ~62k rows it rebuilds in about a second, and rebuilding is what keeps a
-- column added here from being invisible in production.
--
-- This header used to carry a commented-out dbt config suggesting incremental
-- materialization "once volume grows". It was not inert: Jinja is rendered
-- before the SQL is ever parsed, so a config call inside a -- comment still
-- configures the model. This table really was incremental, and because
-- on_schema_change defaults to ignore, adding is_target_role here left
-- production missing the column while every local build passed. If incremental
-- is ever wanted, configure it explicitly at the top of the file and set
-- on_schema_change; do not leave a config in a comment.

with observations as (
    select
        source,
        source_job_id,
        content_hash,
        scraped_at,
        scraped_date,
        company_name,
        country_code,
        title
    from {{ ref('stg_job_postings') }}
),

lifespan as (
    select
        source,
        source_job_id,
        min(scraped_date) as first_seen_date,
        max(scraped_date) as last_seen_date
    from observations
    group by 1, 2
),

-- A posting can be observed more than once per day (re-scrapes, content
-- edits between passes). The grain is per DAY, so collapse to the day's
-- last observation — otherwise two content versions of one job duplicate
-- the snapshot_key.
daily as (
    select
        source,
        source_job_id,
        scraped_date,
        arg_max(content_hash, scraped_at)  as content_hash,
        arg_max(company_name, scraped_at)  as company_name,
        arg_max(country_code, scraped_at)  as country_code,
        arg_max(title, scraped_at)         as title
    from observations
    group by 1, 2, 3
)

select
    {{ dbt_utils.generate_surrogate_key(['d.source', 'd.source_job_id', 'd.scraped_date']) }} as snapshot_key,
    d.scraped_date                                          as date_key,
    {{ dbt_utils.generate_surrogate_key(['d.source']) }}   as source_key,
    {{ dbt_utils.generate_surrogate_key(['d.company_name', 'd.country_code']) }} as company_key,
    d.source,
    d.source_job_id,
    d.content_hash,
    d.company_name,
    d.country_code,
    d.title,
    (d.scraped_date = l.first_seen_date)                   as is_first_seen,
    (d.scraped_date = l.last_seen_date)                    as is_last_seen,
    date_diff('day', l.first_seen_date, d.scraped_date)    as days_since_first_seen,

    -- Same title-based test as the current-state fact, so a trend chart and the
    -- list it is meant to explain cannot disagree about what counts as a data role.
    {{ jmi_is_target_role('d.title') }}                    as is_target_role
from daily d
join lifespan l
    on d.source = l.source
   and d.source_job_id = l.source_job_id
