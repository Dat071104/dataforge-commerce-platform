-- P7.2 Week 5 schema. Run once after Terraform creates the ops dataset.
-- All objects are scoped to the existing staging/silver/gold datasets and the
-- new, narrowly scoped ops dataset in the selected project.

CREATE TABLE IF NOT EXISTS ops.pipeline_checkpoints (
  source_id STRING NOT NULL,
  committed_seq INT64 NOT NULL,
  last_batch_id STRING,
  row_value_sha256 STRING,
  manifest_sha256 STRING,
  manifest_generation INT64,
  object_sha256 STRING,
  object_generation INT64,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS ops.writer_locks (
  lock_name STRING NOT NULL,
  lock_version INT64 NOT NULL,
  touched_at TIMESTAMP NOT NULL,
  last_run_id STRING
);

-- This table is written by INSERT only in the Week-5 SQL/runtime contract.
-- BigQuery dataset-level dataEditor IAM cannot enforce append-only behavior;
-- treat direct UPDATE/DELETE access as a residual operational risk.
CREATE TABLE IF NOT EXISTS ops.week5_run_events (
  event_id STRING NOT NULL,
  run_id STRING NOT NULL,
  execution_id STRING,
  batch_id STRING,
  status STRING NOT NULL,
  run_mode STRING,
  source_run_id STRING,
  event_at TIMESTAMP NOT NULL,
  attempt INT64,
  manifest_uri STRING,
  lower_seq INT64,
  upper_seq INT64,
  expected_row_count INT64,
  row_value_sha256 STRING,
  manifest_sha256 STRING,
  manifest_generation INT64,
  object_sha256 STRING,
  object_generation INT64,
  stage_table_id STRING,
  stage_load_job_id STRING,
  stage_verify_job_id STRING,
  publish_job_id STRING,
  published_check_job_id STRING,
  checkpoint_before INT64,
  checkpoint_after INT64,
  affected_order_count INT64,
  delivered_sales_proxy NUMERIC,
  collected_amount NUMERIC,
  error_code STRING,
  error_message STRING
)
PARTITION BY DATE(event_at)
CLUSTER BY batch_id, run_id;

CREATE TABLE IF NOT EXISTS silver.week5_orders (
  order_id STRING NOT NULL,
  customer_id STRING,
  order_date DATE,
  province_id STRING,
  order_status STRING,
  order_net_amount NUMERIC(18, 2),
  is_deleted BOOL NOT NULL,
  effective_seq INT64 NOT NULL,
  last_change_id STRING NOT NULL,
  last_payload_sha256 STRING NOT NULL,
  source_updated_at TIMESTAMP NOT NULL,
  business_event_at TIMESTAMP NOT NULL,
  last_batch_id STRING NOT NULL,
  ingested_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS silver.week5_payment_events (
  payment_id STRING NOT NULL,
  order_id STRING,
  payment_date DATE,
  amount NUMERIC(18, 2),
  payment_status STRING,
  method STRING,
  is_deleted BOOL NOT NULL,
  effective_seq INT64 NOT NULL,
  last_change_id STRING NOT NULL,
  last_payload_sha256 STRING NOT NULL,
  source_updated_at TIMESTAMP NOT NULL,
  business_event_at TIMESTAMP NOT NULL,
  last_batch_id STRING NOT NULL,
  ingested_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS gold.week5_order_controls (
  order_id STRING NOT NULL,
  customer_id STRING,
  order_date DATE,
  province_id STRING,
  order_status STRING,
  order_is_deleted BOOL NOT NULL,
  delivered_sales_proxy NUMERIC,
  collected_amount NUMERIC NOT NULL,
  collection_variance NUMERIC,
  active_payment_count INT64 NOT NULL,
  successful_payment_count INT64 NOT NULL,
  order_effective_seq INT64 NOT NULL,
  published_batch_id STRING NOT NULL,
  published_run_id STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

-- This logical view reflects retroactive business-date corrections through the
-- affected order rows. Deleted-order collections stay visible separately and
-- are not silently added to active-order variance.
CREATE OR REPLACE VIEW gold.week5_monthly_controls AS
SELECT
  DATE_TRUNC(order_date, MONTH) AS order_month,
  COUNTIF(NOT order_is_deleted) AS active_order_count,
  COUNTIF(order_is_deleted) AS tombstoned_order_count,
  SUM(IF(NOT order_is_deleted, delivered_sales_proxy, CAST(0 AS NUMERIC)))
    AS active_delivered_sales_proxy,
  SUM(IF(NOT order_is_deleted, collected_amount, CAST(0 AS NUMERIC)))
    AS active_order_collections,
  SUM(IF(order_is_deleted, collected_amount, CAST(0 AS NUMERIC)))
    AS collections_for_tombstoned_orders,
  SUM(IF(NOT order_is_deleted, collection_variance, CAST(0 AS NUMERIC)))
    AS active_order_collection_variance
FROM gold.week5_order_controls
WHERE order_date IS NOT NULL
GROUP BY order_month;

-- Idempotent singleton seeds. The publish transaction asserts one row for
-- each key and mutates the writer-lock row before touching business tables.
INSERT INTO ops.pipeline_checkpoints (
  source_id,
  committed_seq,
  updated_at
)
SELECT seed.source_id, seed.initial_seq, CURRENT_TIMESTAMP()
FROM UNNEST([
  STRUCT('dataforge-operational-v1' AS source_id, 0 AS initial_seq)
]) AS seed
WHERE NOT EXISTS (
  SELECT 1
  FROM ops.pipeline_checkpoints
  WHERE source_id = 'dataforge-operational-v1'
);

INSERT INTO ops.writer_locks (
  lock_name,
  lock_version,
  touched_at,
  last_run_id
)
SELECT seed.lock_name, 0, CURRENT_TIMESTAMP(), CAST(NULL AS STRING)
FROM UNNEST([
  STRUCT('dataforge-operational-v1' AS lock_name)
]) AS seed
WHERE NOT EXISTS (
  SELECT 1
  FROM ops.writer_locks
  WHERE lock_name = 'dataforge-operational-v1'
);
