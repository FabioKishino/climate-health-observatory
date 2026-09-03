-- Fact: one row per respiratory-cause hospital admission (AIH record).

with admissions as (
    select * from {{ ref('int_datasus__admissions_enriched') }}
)

select
    aih_number,
    admission_date as fk_date,
    municipality_residence_code as fk_municipality,
    1 as admission_count,  -- always 1, at this grain, to allow sum() downstream
    total_aih_value,
    length_of_stay,
    icd_group
from admissions
