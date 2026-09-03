-- Staging model: DataSUS/SIH-RD hospital admissions.
-- Column renaming and type casting only — municipality and diagnosis
-- filtering already happened in the ingestion layer; ICD grouping and any
-- further business logic happen downstream in intermediate/marts models.

with source as (
    select * from {{ source('datasus', 'admissions') }}
),

renamed as (
    select
        aih_number::varchar as aih_number,
        municipality_residence_code::varchar as municipality_residence_code,
        admission_date::date as admission_date,
        primary_diagnosis::varchar as primary_diagnosis,
        total_aih_value::double as total_aih_value,
        length_of_stay::integer as length_of_stay
    from source
)

select * from renamed
