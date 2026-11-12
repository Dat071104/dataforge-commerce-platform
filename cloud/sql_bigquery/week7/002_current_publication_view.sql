-- P7.4 migration for the currentness fence.
--
-- Run only after Terraform adds `publication_is_current` and the Week-7 version
-- table exists. This view returns rows only while the pointer says that its
-- source state was validated. The immutable versions table is not modified.

CREATE OR REPLACE VIEW `dataforge-p7-lab-d0f725.gold_week7.published_order_reconciliation` AS
SELECT version.*, TRUE AS publication_is_current
FROM `dataforge-p7-lab-d0f725.gold_week7.week7_order_reconciliation_versions` AS version
JOIN `dataforge-p7-lab-d0f725.gold_week7.week7_publication_pointer` AS pointer
  ON pointer.pointer_name = 'current_order_reconciliation'
 AND pointer.publication_id = version.publication_id
WHERE pointer.publication_is_current IS TRUE;
