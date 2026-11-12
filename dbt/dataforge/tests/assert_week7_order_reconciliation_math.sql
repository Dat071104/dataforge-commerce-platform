select
    gold.order_id
from {{ ref('fct_week7_order_reconciliation') }} as gold
join {{ ref('stg_week5_orders') }} as orders using (order_id)
left join {{ ref('int_week5_payment_control_by_order') }} as payments using (order_id)
where gold.order_effective_seq != orders.effective_seq
    or gold.order_is_deleted != orders.is_deleted
    or gold.delivered_sales_proxy != if(
        orders.is_deleted or orders.order_status != 'delivered',
        cast(0 as numeric),
        coalesce(orders.order_net_amount, cast(0 as numeric))
    )
    or gold.collected_amount != coalesce(payments.collected_amount, cast(0 as numeric))
    or gold.active_payment_count != coalesce(payments.active_payment_count, 0)
    or gold.successful_payment_count != coalesce(payments.successful_payment_count, 0)
    or gold.max_payment_effective_seq != coalesce(payments.max_payment_effective_seq, 0)
    or (
        orders.is_deleted
        and gold.collection_variance is not null
    )
    or (
        not orders.is_deleted
        and gold.collection_variance
            != gold.collected_amount - gold.delivered_sales_proxy
    )
