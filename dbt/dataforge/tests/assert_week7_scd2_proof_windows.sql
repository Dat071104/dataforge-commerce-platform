{{ config(tags=['scd2_proof']) }}

with history as (
    select *
    from {{ ref('week7_scd2_proof_history') }}
), invalid_intervals as (
    select
        a.order_id,
        a.dbt_scd_id as left_scd_id,
        b.dbt_scd_id as right_scd_id,
        a.dbt_valid_from as left_valid_from,
        a.dbt_valid_to as left_valid_to,
        b.dbt_valid_from as right_valid_from,
        b.dbt_valid_to as right_valid_to
    from history as a
    join history as b
      on a.order_id = b.order_id
     and a.dbt_scd_id < b.dbt_scd_id
     and a.dbt_valid_from < coalesce(b.dbt_valid_to, timestamp('9999-12-31 00:00:00+00'))
     and b.dbt_valid_from < coalesce(a.dbt_valid_to, timestamp('9999-12-31 00:00:00+00'))
)
select * from invalid_intervals
