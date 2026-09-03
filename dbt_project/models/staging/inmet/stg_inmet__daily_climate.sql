-- Staging model: INMET daily climate readings.
-- Column renaming and type casting only — no aggregation, filtering, or
-- other business logic (that already happened in the ingestion layer, or
-- happens downstream in intermediate/marts models).

with source as (
    select * from {{ source('inmet', 'daily_climate') }}
),

renamed as (
    select
        station_code::varchar as station_code,
        date::date as date_day,
        station_name::varchar as station_name,
        state::varchar as state,
        latitude::double as latitude,
        longitude::double as longitude,
        avg_temp::double as avg_temp,
        min_temp::double as min_temp,
        max_temp::double as max_temp,
        avg_relative_humidity::double as avg_relative_humidity,
        total_precipitation::double as total_precipitation
    from source
)

select * from renamed
