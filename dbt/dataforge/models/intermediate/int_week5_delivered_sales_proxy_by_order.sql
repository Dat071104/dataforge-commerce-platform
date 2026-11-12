select
    order_id,
    customer_id,
    order_date,
    province_id,
    order_status,
    is_deleted as order_is_deleted,
    effective_seq as order_effective_seq,
    ingested_at as order_ingested_at,
    if(
        is_deleted or order_status != 'delivered',
        cast(0 as numeric),
        coalesce(order_net_amount, cast(0 as numeric))
    ) as delivered_sales_proxy
from {{ ref('stg_week5_orders') }}
