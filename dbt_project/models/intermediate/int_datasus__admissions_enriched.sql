-- Intermediate model: enriches staged admissions with derived business
-- fields. This is where business logic belongs (unlike staging) — here,
-- classifying the primary diagnosis into an ICD-10 category.

with admissions as (
    select * from {{ ref('stg_datasus__admissions') }}
),

enriched as (
    select
        *,
        -- ICD-10 3-character category (e.g. "J18" = pneumonia, unspecified
        -- organism; "J45" = asthma) — one level above the full code, and
        -- the standard granularity for grouping ICD-10 diagnoses.
        left(primary_diagnosis, 3) as icd_group
    from admissions
)

select * from enriched
