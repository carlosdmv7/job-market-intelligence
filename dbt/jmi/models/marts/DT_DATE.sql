-- Date dimension spanning project start through tomorrow.

with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2026-01-01' as date)",
        end_date="cast(current_date + interval 1 day as date)"
    ) }}
)

select
    cast(date_day as date)                                   as date_key,
    extract(year  from date_day)                            as year,
    extract(month from date_day)                            as month,
    extract(day   from date_day)                            as day_of_month,
    strftime(date_day, '%Y-%m')                             as year_month,
    extract(dow from date_day)                              as day_of_week,
    extract(dow from date_day) in (0, 6)                    as is_weekend
from spine
