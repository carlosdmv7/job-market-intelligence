-- A corpus with no active posting means the liveness signal is broken, not
-- that the EU stopped hiring.
--
-- `is_active` is derived from the corpus's newest observation
-- (`max(scraped_at)`), deliberately not from `current_date`, so a stalled
-- pipeline cannot mark the whole market closed on a calendar technicality.
-- The failure mode that replaces it is subtler: if that CTE ever computes the
-- wrong anchor, *every* row goes inactive at once, the app shows "0 open data
-- roles" on every page, and every `not_null` and range test still passes —
-- because "false everywhere" is a perfectly valid boolean column.
--
-- The `having count(*) > 0` guard is what makes this safe in CI, which builds
-- the whole DAG against an empty DuckDB: no rows means nothing to assert, not
-- a failure.

select
    count(*)                                as postings,
    count(*) filter (where is_active)       as active
from {{ ref('FT_JOB_POSTING') }}
having count(*) > 0
   and count(*) filter (where is_active) = 0
