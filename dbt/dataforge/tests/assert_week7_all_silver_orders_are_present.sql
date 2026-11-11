select
    source.order_id
from {{ ref('stg_week5_orders') }} as source
left join {{ ref('fct_week7_order_reconciliation') }} as target using (order_id)
where target.order_id is null
