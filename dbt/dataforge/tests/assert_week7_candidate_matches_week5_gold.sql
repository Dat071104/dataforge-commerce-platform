with candidate as (
    select
        order_id,
        customer_id,
        order_date,
        province_id,
        order_status,
        order_is_deleted,
        delivered_sales_proxy,
        collected_amount,
        collection_variance,
        active_payment_count,
        successful_payment_count,
        order_effective_seq
    from {{ ref('fct_week7_order_reconciliation') }}
),
week5_gold as (
    select
        order_id,
        customer_id,
        order_date,
        province_id,
        order_status,
        order_is_deleted,
        delivered_sales_proxy,
        collected_amount,
        collection_variance,
        active_payment_count,
        successful_payment_count,
        order_effective_seq
    from {{ source('week5_gold', 'week5_order_controls') }}
)
select
    coalesce(candidate.order_id, week5_gold.order_id) as order_id
from candidate
full outer join week5_gold
    on candidate.order_id = week5_gold.order_id
where candidate.order_id is null
    or week5_gold.order_id is null
    or candidate.customer_id is distinct from week5_gold.customer_id
    or candidate.order_date is distinct from week5_gold.order_date
    or candidate.province_id is distinct from week5_gold.province_id
    or candidate.order_status is distinct from week5_gold.order_status
    or candidate.order_is_deleted is distinct from week5_gold.order_is_deleted
    or candidate.delivered_sales_proxy is distinct from week5_gold.delivered_sales_proxy
    or candidate.collected_amount is distinct from week5_gold.collected_amount
    or candidate.collection_variance is distinct from week5_gold.collection_variance
    or candidate.active_payment_count is distinct from week5_gold.active_payment_count
    or candidate.successful_payment_count is distinct from week5_gold.successful_payment_count
    or candidate.order_effective_seq is distinct from week5_gold.order_effective_seq
