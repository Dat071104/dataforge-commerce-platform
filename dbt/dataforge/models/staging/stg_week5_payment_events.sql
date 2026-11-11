select
    payment_id,
    order_id,
    payment_date,
    cast(amount as numeric) as amount,
    payment_status,
    method,
    is_deleted,
    effective_seq,
    last_change_id,
    last_payload_sha256,
    source_updated_at,
    business_event_at,
    last_batch_id,
    ingested_at
from {{ source('week5_silver', 'week5_payment_events') }}
