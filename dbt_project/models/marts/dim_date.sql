-- Dimension: one row per calendar day. Deliberately wider than the
-- project's 24-month scope (2020-01-01 through one year from today) so the
-- dimension never needs a rebuild just because new data arrives.

with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2020-01-01' as date)",
        end_date="cast(current_date + interval 1 year as date)"
    ) }}
),

enriched as (
    select
        cast(date_day as date) as date_day,
        extract(year from date_day) as year,
        extract(month from date_day) as month,
        extract(day from date_day) as day,
        dayofweek(date_day) as day_of_week,
        strftime(date_day, '%B') as month_name,
        case
            -- Southern Hemisphere meteorological seasons.
            when extract(month from date_day) in (12, 1, 2) then 'Summer'
            when extract(month from date_day) in (3, 4, 5) then 'Autumn'
            when extract(month from date_day) in (6, 7, 8) then 'Winter'
            when extract(month from date_day) in (9, 10, 11) then 'Spring'
        end as season
    from spine
)

select * from enriched
