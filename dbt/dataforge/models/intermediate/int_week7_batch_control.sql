with events as (
    select *
    from {{ ref('stg_week5_run_events') }}
),
per_run as (
    select
        run_id,
        any_value(batch_id) as batch_id,
        any_value(run_mode) as run_mode,
        any_value(source_run_id) as source_run_id,
        min(event_at) as first_event_at,
        max(event_at) as last_event_at,
        count(*) as event_count,
        countif(status = 'DISCOVERED') as discovered_event_count,
        countif(status = 'VALIDATED') as validated_event_count,
        countif(status = 'STAGED') as staged_event_count,
        countif(status = 'CHECKED') as checked_event_count,
        countif(status = 'PUBLISHED') as published_event_count,
        countif(status = 'NO_OP') as no_op_event_count,
        countif(status = 'FAILED') as failed_event_count,
        max(if(status = 'PUBLISHED', upper_seq, null)) as published_upper_seq,
        max(if(status = 'PUBLISHED', manifest_generation, null)) as published_manifest_generation,
        max(if(status = 'PUBLISHED', checkpoint_after, null)) as published_checkpoint_after,
        max(if(status = 'PUBLISHED', affected_order_count, null)) as published_affected_order_count,
        array_agg(error_code ignore nulls order by event_at desc limit 1)[safe_offset(0)]
            as latest_error_code,
        array_agg(error_message ignore nulls order by event_at desc limit 1)[safe_offset(0)]
            as latest_error_message
    from events
    group by run_id
),
checkpoint as (
    select
        source_id,
        committed_seq as current_committed_seq
    from {{ ref('stg_week5_pipeline_checkpoints') }}
)
select
    run.run_id,
    run.batch_id,
    run.run_mode,
    run.source_run_id,
    run.first_event_at,
    run.last_event_at,
    run.event_count,
    run.discovered_event_count,
    run.validated_event_count,
    run.staged_event_count,
    run.checked_event_count,
    run.published_event_count,
    run.no_op_event_count,
    run.failed_event_count,
    run.published_upper_seq,
    run.published_manifest_generation,
    run.published_checkpoint_after,
    run.published_affected_order_count,
    checkpoint.current_committed_seq,
    case
        when run.published_event_count > 0 and run.failed_event_count > 0 then 'PUBLISHED_WITH_RETRY'
        when run.published_event_count > 0 then 'PUBLISHED'
        when run.no_op_event_count > 0 then 'NO_OP'
        when run.failed_event_count > 0 then 'FAILED'
        when run.staged_event_count > 0 then 'STAGED'
        when run.validated_event_count > 0 then 'VALIDATED'
        else 'DISCOVERED'
    end as run_outcome,
    (
        run.published_event_count = 0
        or (
            run.checked_event_count > 0
            and run.published_checkpoint_after is not null
            and (
                run.run_mode = 'backfill'
                or run.published_checkpoint_after >= run.published_upper_seq
            )
        )
    ) as publish_quality_gate_passed,
    run.latest_error_code,
    run.latest_error_message
from per_run as run
left join checkpoint
    on checkpoint.source_id = 'dataforge-operational-v1'
