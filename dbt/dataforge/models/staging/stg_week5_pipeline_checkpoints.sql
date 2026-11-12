select
    source_id,
    committed_seq,
    last_batch_id,
    row_value_sha256,
    manifest_sha256,
    manifest_generation,
    object_sha256,
    object_generation,
    updated_at
from {{ source('week5_ops', 'pipeline_checkpoints') }}
