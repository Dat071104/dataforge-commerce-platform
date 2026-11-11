select
    payment.payment_id,
    payment.order_id
from {{ ref('int_week5_current_payments') }} as payment
left join {{ ref('stg_week5_orders') }} as order_row
    on payment.order_id = order_row.order_id
where not payment.is_deleted
    and (payment.order_id is null or order_row.order_id is null)
