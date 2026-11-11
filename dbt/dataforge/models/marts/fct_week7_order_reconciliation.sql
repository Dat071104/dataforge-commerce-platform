{{
    config(
        materialized='incremental',
        incremental_strategy='merge',
        unique_key='order_id',
        partition_by={
            'field': 'order_id_bucket',
            'data_type': 'int64',
            'range': {'start': 0, 'end': 64, 'interval': 1}
        },
        cluster_by=['order_id'],
        incremental_predicates=[
            'DBT_INTERNAL_DEST.order_id_bucket = DBT_INTERNAL_SOURCE.order_id_bucket'
        ],
        on_schema_change='fail',
        require_partition_filter=false,
        labels={'application': 'dataforge', 'phase': 'week7'}
    )
}}

with orders as (
    select *
    from {{ ref('int_week5_delivered_sales_proxy_by_order') }}
),
payment_control as (
    select *
    from {{ ref('int_week5_payment_control_by_order') }}
),
previous as (
    {% if is_incremental() %}
    select
        order_id,
        order_effective_seq,
        max_payment_effective_seq
    from {{ this }}
    {% else %}
    select
        cast(null as string) as order_id,
        cast(null as int64) as order_effective_seq,
        cast(null as int64) as max_payment_effective_seq
    from unnest([1]) as _seed
    where false
    {% endif %}
),
impacted_order_ids as (
    {% if is_incremental() %}
    select current_order.order_id
    from orders as current_order
    left join previous as prior using (order_id)
    left join payment_control as payment using (order_id)
    where prior.order_id is null
        or current_order.order_effective_seq != prior.order_effective_seq
        or coalesce(payment.max_payment_effective_seq, 0)
            != prior.max_payment_effective_seq
    {% else %}
    select order_id
    from orders
    {% endif %}
),
quality_gate as (
    select
        not exists (
            select order_id
            from {{ ref('stg_week5_orders') }}
            group by order_id
            having count(*) > 1
        )
        and not exists (
            select payment_id
            from {{ ref('stg_week5_payment_events') }}
            group by payment_id
            having count(*) > 1
        )
        and not exists (
            select 1
            from {{ ref('int_week5_current_payments') }} as payment
            left join {{ ref('stg_week5_orders') }} as order_row
                on payment.order_id = order_row.order_id
            where not payment.is_deleted
                and (payment.order_id is null or order_row.order_id is null)
        )
        and not exists (
            select 1
            from {{ ref('int_week7_batch_control') }}
            where not publish_quality_gate_passed
        ) as passed
),
assembled as (
    select
        orders.order_id,
        orders.customer_id,
        orders.order_date,
        orders.province_id,
        orders.order_status,
        orders.order_is_deleted,
        orders.delivered_sales_proxy,
        coalesce(payment.collected_amount, cast(0 as numeric)) as collected_amount,
        if(
            orders.order_is_deleted,
            cast(null as numeric),
            coalesce(payment.collected_amount, cast(0 as numeric))
                - orders.delivered_sales_proxy
        ) as collection_variance,
        coalesce(payment.active_payment_count, 0) as active_payment_count,
        coalesce(payment.successful_payment_count, 0) as successful_payment_count,
        orders.order_effective_seq,
        coalesce(payment.max_payment_effective_seq, 0) as max_payment_effective_seq,
        mod(mod(farm_fingerprint(orders.order_id), 64) + 64, 64) as order_id_bucket,
        orders.order_ingested_at,
        coalesce(
            payment.latest_payment_ingested_at,
            timestamp '1970-01-01 00:00:00+00'
        ) as latest_payment_ingested_at
    from orders
    left join payment_control as payment using (order_id)
    inner join impacted_order_ids using (order_id)
)
select assembled.*
from assembled
cross join quality_gate
where quality_gate.passed
