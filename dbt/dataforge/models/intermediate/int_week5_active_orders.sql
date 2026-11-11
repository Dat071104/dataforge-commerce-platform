select
    order_id,
    customer_id,
    order_date,
    province_id,
    order_status,
    order_net_amount,
    effective_seq as order_effective_seq,
    ingested_at as order_ingested_at
from {{ ref('stg_week5_orders') }}
where not is_deleted
