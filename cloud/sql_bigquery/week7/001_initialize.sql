-- P7.4 one-time Week-7 control bootstrap.
--
-- Apply this only after Terraform creates the Week-7 datasets/tables and before
-- the first workflow invocation. The script inserts only missing singleton
-- rows. It never clears an active lease or resets an existing publication
-- pointer. A newly added nullable publication-currentness flag is initialized
-- to FALSE only when it is NULL, keeping unknown status fail-closed.
--
-- Approved scope: dataforge-p7-lab-d0f725 / us-central1, synthetic Week-5
-- operational-journal data only. This script does not create or drop objects.

DECLARE v_lock_rows INT64;
DECLARE v_pointer_rows INT64;

BEGIN TRANSACTION;

SET v_lock_rows = (
  SELECT COUNT(*)
  FROM `dataforge-p7-lab-d0f725.ops.week7_publish_lock`
);
SET v_pointer_rows = (
  SELECT COUNT(*)
  FROM `dataforge-p7-lab-d0f725.gold_week7.week7_publication_pointer`
);

ASSERT v_lock_rows <= 1
  AS 'Week-7 publication lock table contains duplicate singleton rows; stop and review.';
ASSERT v_pointer_rows <= 1
  AS 'Week-7 publication pointer table contains duplicate singleton rows; stop and review.';
ASSERT NOT EXISTS (
  SELECT 1
  FROM `dataforge-p7-lab-d0f725.ops.week7_publish_lock`
  WHERE lock_name != 'week7-dbt-publication'
)
  AS 'Week-7 publication lock table contains an unexpected lock name.';
ASSERT NOT EXISTS (
  SELECT 1
  FROM `dataforge-p7-lab-d0f725.gold_week7.week7_publication_pointer`
  WHERE pointer_name != 'current_order_reconciliation'
)
  AS 'Week-7 publication pointer table contains an unexpected pointer name.';

IF v_lock_rows = 0 THEN
  INSERT INTO `dataforge-p7-lab-d0f725.ops.week7_publish_lock` (
    lock_name,
    lock_owner,
    lock_expires_at,
    lock_version,
    updated_at
  )
  VALUES (
    'week7-dbt-publication',
    NULL,
    NULL,
    0,
    CURRENT_TIMESTAMP()
  );
END IF;

IF v_pointer_rows = 0 THEN
  INSERT INTO `dataforge-p7-lab-d0f725.gold_week7.week7_publication_pointer` (
    pointer_name,
    pointer_version,
    published_run_mode,
    publication_id,
    published_run_id,
    batch_id,
    manifest_generation,
    upper_seq,
    source_checkpoint_seq,
    candidate_dataset,
    candidate_row_count,
    candidate_sha256,
    published_at,
    publication_is_current
  )
  VALUES (
    'current_order_reconciliation',
    0,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    NULL,
    FALSE
  );
END IF;

UPDATE `dataforge-p7-lab-d0f725.gold_week7.week7_publication_pointer`
SET publication_is_current = FALSE
WHERE pointer_name = 'current_order_reconciliation'
  AND publication_is_current IS NULL;

ASSERT (
  SELECT COUNT(*) = 1
    AND COUNTIF(lock_version < 0) = 0
    AND COUNTIF((lock_owner IS NULL) != (lock_expires_at IS NULL)) = 0
  FROM `dataforge-p7-lab-d0f725.ops.week7_publish_lock`
  WHERE lock_name = 'week7-dbt-publication'
)
  AS 'Week-7 lock singleton is missing or contains incompatible state.';
ASSERT (
  SELECT COUNT(*) = 1
    AND COUNTIF(pointer_version < 0) = 0
    AND COUNTIF(pointer_version = 0 AND (
      publication_id IS NOT NULL
      OR published_run_mode IS NOT NULL
      OR published_run_id IS NOT NULL
      OR batch_id IS NOT NULL
      OR manifest_generation IS NOT NULL
      OR upper_seq IS NOT NULL
      OR source_checkpoint_seq IS NOT NULL
      OR candidate_dataset IS NOT NULL
      OR candidate_row_count IS NOT NULL
      OR candidate_sha256 IS NOT NULL
      OR published_at IS NOT NULL
      OR publication_is_current IS NOT FALSE
    )) = 0
    AND COUNTIF(pointer_version > 0 AND (
      publication_id IS NULL
      OR published_run_mode IS NULL
      OR published_run_mode NOT IN ('normal', 'backfill')
      OR published_run_id IS NULL
      OR batch_id IS NULL
      OR manifest_generation IS NULL
      OR upper_seq IS NULL
      OR source_checkpoint_seq IS NULL
      OR candidate_dataset IS NULL
      OR candidate_row_count IS NULL
      OR candidate_sha256 IS NULL
      OR published_at IS NULL
      OR publication_is_current IS NULL
    )) = 0
  FROM `dataforge-p7-lab-d0f725.gold_week7.week7_publication_pointer`
  WHERE pointer_name = 'current_order_reconciliation'
)
  AS 'Week-7 pointer singleton is missing or contains incompatible state.';

COMMIT TRANSACTION;
