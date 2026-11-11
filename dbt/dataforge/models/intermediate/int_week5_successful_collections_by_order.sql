select
    order_id,
    successful_payment_count,
    collected_amount
from {{ ref('int_week5_payment_control_by_order') }}
