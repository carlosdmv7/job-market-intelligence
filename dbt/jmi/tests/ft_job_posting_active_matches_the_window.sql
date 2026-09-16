-- `is_active` and `days_since_seen` are two renderings of one fact, and the
-- app leans on both: it filters lists by the flag and explains the filter with
-- the number ("last seen 3 days ago"). They are computed by two separate
-- expressions in FT_JOB_POSTING, so nothing but this test stops one from being
-- edited without the other — at which point the app would go on calling a
-- posting open while showing, in the same card, that nobody has seen it for
-- six weeks.
--
-- Row-wise, so an empty warehouse passes it vacuously and CI stays honest.

select
    job_posting_key,
    days_since_seen,
    is_active
from {{ ref('FT_JOB_POSTING') }}
where is_active != (days_since_seen <= {{ var('active_window_days', 7) }})
