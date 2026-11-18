{{ config(schema='pii_safe', alias='dim_customer_profile_safe', materialized='table') }}

select
    customer_token,
    age_band,
    province_id,
    {{ pii_mask_email('email') }} as email_masked,
    data_classification
from {{ source('restricted_pii', 'customer_profile') }}
where data_classification = 'synthetic'
