-- Analysis mart: daily climate joined to daily respiratory admission
-- counts, the base table for the "does climate variation correlate with
-- admission spikes" question this project exists to answer.
--
-- Grain: one row per (date, station). Admissions are per-admission in
-- fct_respiratory_admissions, so they're aggregated to daily counts here
-- and joined via dim_date, plus a municipality -> nearest station lookup
-- (see seeds/municipality_station_mapping.csv) since fct_daily_climate has
-- no municipality of its own — not every municipality has a weather
-- station, so this project approximates "the municipality's climate" as
-- "its nearest station's climate" (see docs/adr for the full rationale).
--
-- A full outer join is used so a day shows up here whether it has climate
-- data, admission data, or (eventually, in the steady state) both —
-- exactly the sparse-data shape you'd expect from DataSUS's ~2-month
-- publication lag versus INMET's ~1-day lag.

with daily_admissions as (
    select
        fk_date,
        fk_municipality,
        sum(admission_count) as daily_admission_count,
        sum(total_aih_value) as daily_total_aih_value,
        avg(length_of_stay) as avg_length_of_stay
    from {{ ref('fct_respiratory_admissions') }}
    group by fk_date, fk_municipality
),

municipality_station as (
    select * from {{ ref('municipality_station_mapping') }}
),

daily_admissions_with_station as (
    select
        daily_admissions.*,
        municipality_station.station_code
    from daily_admissions
    left join municipality_station
        on daily_admissions.fk_municipality = municipality_station.municipality_ibge_code
),

climate as (
    select * from {{ ref('fct_daily_climate') }}
),

joined as (
    select
        coalesce(daily_admissions_with_station.fk_date, climate.fk_date) as date_day,
        coalesce(daily_admissions_with_station.station_code, climate.fk_station) as station_code,
        daily_admissions_with_station.fk_municipality,
        climate.avg_temp,
        climate.min_temp,
        climate.max_temp,
        climate.avg_relative_humidity,
        climate.total_precipitation,
        coalesce(daily_admissions_with_station.daily_admission_count, 0) as daily_admission_count,
        daily_admissions_with_station.daily_total_aih_value,
        daily_admissions_with_station.avg_length_of_stay
    from daily_admissions_with_station
    full outer join climate
        on daily_admissions_with_station.fk_date = climate.fk_date
        and daily_admissions_with_station.station_code = climate.fk_station
)

select * from joined
