-- Dimension: one row per municipality present in the admissions data,
-- enriched with name/state/coordinates from the municipalities seed and a
-- region derived from state (see macros/get_brazil_region.sql — modeled as
-- a derivation, not a static column, so it keeps working if the state
-- scope expands beyond Parana).

with admissions_municipalities as (
    select distinct municipality_residence_code
    from {{ ref('stg_datasus__admissions') }}
),

enriched as (
    select
        m.municipality_residence_code as ibge_code,
        seed.municipality_name as municipality,
        seed.state,
        {{ get_brazil_region('seed.state') }} as region,
        seed.latitude,
        seed.longitude
    from admissions_municipalities m
    left join {{ ref('municipalities') }} seed
        on m.municipality_residence_code = seed.ibge_code
)

select * from enriched
