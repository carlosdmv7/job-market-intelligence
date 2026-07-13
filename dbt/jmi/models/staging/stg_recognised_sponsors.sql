-- IND recognised-sponsor register (Netherlands), from the seed. One row per
-- normalized company name, so it can be left-joined as a lookup. The normalized
-- key is built with the same macro applied to job-posting company names.

with seed as (
    select * from {{ ref('recognised_sponsors') }}
),

normalized as (
    select
        organisation,
        kvk_number,
        {{ jmi_normalize_company('organisation') }} as company_norm
    from seed
    where organisation is not null
)

select
    company_norm,
    min(organisation) as organisation,   -- representative display name
    min(kvk_number)   as kvk_number
from normalized
where company_norm <> ''
group by company_norm
