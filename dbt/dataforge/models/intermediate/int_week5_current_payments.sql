select
    payment_id,
    order_id,
    payment_date,
    amount,
    payment_status,
    method,
    is_deleted,
    effective_seq as payment_effective_seq,
    ingested_at as payment_ingested_at
from {{ ref('stg_week5_payment_events') }}
