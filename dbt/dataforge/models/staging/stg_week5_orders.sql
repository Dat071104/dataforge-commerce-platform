select
    order_id,
    customer_id,
    order_date,
    province_id,
    order_status,
    cast(order_net_amount as numeric) as order_net_amount,
    is_deleted,
    effective_seq,
    last_change_id,
    last_payload_sha256,
    source_updated_at,
    business_event_at,
    last_batch_id,
    ingested_at
from {{ source('week5_silver', 'week5_orders') }}
