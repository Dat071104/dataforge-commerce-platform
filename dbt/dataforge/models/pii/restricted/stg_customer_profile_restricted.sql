{{
    config(
        schema='restricted_pii',
        alias='customer_profile_restricted',
        materialized='view',
    )
}}

select
    fixture_id,
    customer_token,
    full_name,
    cccd,
    email,
    phone,
    birth_date,
    province_id,
    age_band,
    data_classification,
    generated_at
from {{ source('restricted_pii', 'customer_profile') }}
