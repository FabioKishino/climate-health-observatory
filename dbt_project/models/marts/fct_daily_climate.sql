-- Fact: one row per weather station per day.

with climate as (
    select * from {{ ref('stg_inmet__daily_climate') }}
)

select
    date_day as fk_date,
    station_code as fk_station,
    avg_temp,
    min_temp,
    max_temp,
    avg_relative_humidity,
    total_precipitation
from climate
