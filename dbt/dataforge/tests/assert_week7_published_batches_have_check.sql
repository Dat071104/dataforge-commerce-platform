select
    run_id
from {{ ref('int_week7_batch_control') }}
where not publish_quality_gate_passed
