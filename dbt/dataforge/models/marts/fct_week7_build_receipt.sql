{{ config(materialized='table', tags=['week7', 'publication']) }}

{% set workflow_run_id = var('workflow_run_id', 'offline-run') | string %}
{% set workflow_run_id = workflow_run_id | replace("'", "''") %}
{% set batch_id = var('batch_id', 'offline-unset') | string %}
{% set batch_id = batch_id | replace("'", "''") %}
{% set run_mode = var('run_mode', 'normal') | string %}
{% set run_mode = run_mode | replace("'", "''") %}
{% if var('test_fail_dbt_build', false) %}
    {{ exceptions.raise_compiler_error('INJECTED_DBT_TRANSFORMATION_FAILURE') }}
{% endif %}

with candidate_rows as (
    select
        order_id,
        order_id_bucket,
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
        order_effective_seq,
        max_payment_effective_seq,
        order_ingested_at,
        latest_payment_ingested_at
    from {{ ref('fct_week7_order_reconciliation') }}
),
source_checkpoint as (
    select max(committed_seq) as source_checkpoint_seq
    from {{ ref('stg_week5_pipeline_checkpoints') }}
    where source_id = 'dataforge-operational-v1'
),
row_hashes as (
    select
        order_id,
        order_id_bucket,
        to_hex(sha256(cast(to_json_string(struct(
            order_id,
            order_id_bucket,
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
            order_effective_seq,
            max_payment_effective_seq,
            order_ingested_at,
            latest_payment_ingested_at
        )) as bytes))) as row_sha256
    from candidate_rows
),
bucket_hashes as (
    select
        order_id_bucket,
        to_hex(sha256(cast(string_agg(row_sha256, '|' order by order_id) as bytes)))
            as bucket_sha256
    from row_hashes
    group by order_id_bucket
),
candidate_metrics as (
    select
        (select count(*) from candidate_rows) as candidate_row_count,
        to_hex(sha256(cast(coalesce(
            (
                select string_agg(
                    concat(cast(order_id_bucket as string), ':', bucket_sha256),
                    '|' order by order_id_bucket
                )
                from bucket_hashes
            ),
            ''
        ) as bytes))) as candidate_sha256
)
select
    cast('{{ workflow_run_id }}' as string) as workflow_run_id,
    cast('{{ batch_id }}' as string) as batch_id,
    cast('{{ run_mode }}' as string) as run_mode,
    cast({{ var('manifest_generation', 0) }} as int64) as manifest_generation,
    cast({{ var('upper_seq', 0) }} as int64) as upper_seq,
    cast('{{ target.database }}' as string) as candidate_project,
    cast('{{ target.schema }}' as string) as candidate_dataset,
    cast('{{ invocation_id }}' as string) as build_invocation_id,
    candidate_metrics.candidate_row_count,
    candidate_metrics.candidate_sha256,
    source_checkpoint.source_checkpoint_seq,
    current_timestamp() as built_at
from candidate_metrics
cross join source_checkpoint
