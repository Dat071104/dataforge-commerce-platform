{% snapshot week7_scd2_proof_history %}

{{
    config(
        unique_key='order_id',
        strategy='timestamp',
        updated_at='updated_at',
        target_schema='dbt_scd2_proof_history',
        invalidate_hard_deletes=false,
        tags=['week7', 'scd2_proof']
    )
}}

select
    order_id,
    order_status,
    order_amount,
    is_deleted,
    business_effective_at,
    updated_at
from {{ source('scd2_proof_input', 'orders') }}

{% endsnapshot %}
