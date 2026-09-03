-- Dimension: one row per weather station present in the climate data, with
-- code, name, and coordinates as captured directly from INMET's API (see
-- ingestion/inmet/extract.py) — no external enrichment needed here, unlike
-- dim_location.

with stations as (
    select distinct
        station_code,
        station_name,
        state,
        latitude,
        longitude
    from {{ ref('stg_inmet__daily_climate') }}
)

select * from stations
