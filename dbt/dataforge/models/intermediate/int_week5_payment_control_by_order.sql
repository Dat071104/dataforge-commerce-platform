select
    order_id,
    max(payment_effective_seq) as max_payment_effective_seq,
    countif(not is_deleted) as active_payment_count,
    countif(not is_deleted and payment_status = 'success') as successful_payment_count,
    sum(
        if(
            not is_deleted and payment_status = 'success',
            coalesce(amount, cast(0 as numeric)),
            cast(0 as numeric)
        )
    ) as collected_amount,
    max(payment_ingested_at) as latest_payment_ingested_at
from {{ ref('int_week5_current_payments') }}
where order_id is not null
group by order_id
