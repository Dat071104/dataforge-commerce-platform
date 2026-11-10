-- P7.2 Week 5 atomic Silver/Gold/checkpoint publication.
--
-- Identifier substitution is limited to the single token below. The runtime
-- must replace it with a backtick-quoted
-- fully qualified identifier generated from the fixed project ID and the
-- validated lowercase-hex batch ID:
--   `PROJECT_ID.staging.week5_events_<first 16 batch-id hex chars>`
-- Never interpolate manifest or other untrusted values into an identifier.
-- All data values below use the named query parameters declared here.
--
-- Required parameters:
--   run_id STRING, batch_id STRING, run_mode STRING (normal|backfill),
--   execution_id STRING, source_run_id STRING, attempt INT64, manifest_uri STRING,
--   lower_seq INT64, upper_seq INT64, row_value_sha256 STRING,
--   manifest_sha256 STRING, manifest_generation INT64,
--   object_sha256 STRING, object_generation INT64,
--   expected_row_count INT64, stage_table_id STRING,
--   stage_load_job_id STRING, stage_verify_job_id STRING,
--   publish_job_id STRING, published_check_job_id STRING,
--   fail_after_merge_once BOOL,
--   fail_before_publish BOOL.
--
-- The runtime verifies the canonical ordered row-value digest before calling
-- this script. Here we independently validate each payload digest, event
-- identities, schema version, post-image shape, and exact sequence bounds.

DECLARE p_run_id STRING DEFAULT @run_id;
DECLARE p_execution_id STRING DEFAULT @execution_id;
DECLARE p_batch_id STRING DEFAULT @batch_id;
DECLARE p_run_mode STRING DEFAULT @run_mode;
DECLARE p_source_run_id STRING DEFAULT @source_run_id;
DECLARE p_attempt INT64 DEFAULT @attempt;
DECLARE p_manifest_uri STRING DEFAULT @manifest_uri;
DECLARE p_lower_seq INT64 DEFAULT @lower_seq;
DECLARE p_upper_seq INT64 DEFAULT @upper_seq;
DECLARE p_row_value_sha256 STRING DEFAULT @row_value_sha256;
DECLARE p_manifest_sha256 STRING DEFAULT @manifest_sha256;
DECLARE p_manifest_generation INT64 DEFAULT @manifest_generation;
DECLARE p_object_sha256 STRING DEFAULT @object_sha256;
DECLARE p_object_generation INT64 DEFAULT @object_generation;
DECLARE p_expected_row_count INT64 DEFAULT @expected_row_count;
DECLARE p_stage_table_id STRING DEFAULT @stage_table_id;
DECLARE p_stage_load_job_id STRING DEFAULT @stage_load_job_id;
DECLARE p_stage_verify_job_id STRING DEFAULT @stage_verify_job_id;
DECLARE p_publish_job_id STRING DEFAULT @publish_job_id;
DECLARE p_published_check_job_id STRING DEFAULT @published_check_job_id;
DECLARE p_fail_after_merge_once BOOL DEFAULT @fail_after_merge_once;
DECLARE p_fail_before_publish BOOL DEFAULT @fail_before_publish;

DECLARE v_already_published BOOL DEFAULT FALSE;
DECLARE v_should_fail_after_merge BOOL DEFAULT FALSE;
DECLARE v_stage_count INT64 DEFAULT 0;
DECLARE v_checkpoint_seq INT64 DEFAULT NULL;
DECLARE v_lock_rows INT64 DEFAULT 0;
DECLARE v_checkpoint_rows INT64 DEFAULT 0;
DECLARE v_checkpoint_after INT64 DEFAULT NULL;
DECLARE v_affected_order_ids ARRAY<STRING> DEFAULT [];
DECLARE v_affected_order_count INT64 DEFAULT 0;
DECLARE v_affected_delivered_sales_proxy NUMERIC DEFAULT 0;
DECLARE v_affected_collected_amount NUMERIC DEFAULT 0;

ASSERT p_run_id IS NOT NULL AND LENGTH(p_run_id) BETWEEN 1 AND 128
  AS 'run_id must be a non-empty identifier of at most 128 characters';
ASSERT p_execution_id IS NOT NULL AND LENGTH(p_execution_id) BETWEEN 1 AND 256
  AS 'execution_id must be a non-empty Cloud Run execution identifier';
ASSERT p_batch_id IS NOT NULL AND REGEXP_CONTAINS(p_batch_id, r'^[0-9a-f]{64}$')
  AS 'batch_id must be a lowercase 64-character SHA-256 hex digest';
ASSERT p_run_mode IN ('normal', 'backfill')
  AS 'run_mode must be normal or backfill';
ASSERT p_source_run_id = CONCAT('dataforge-operational-v1:', p_batch_id)
  AS 'source_run_id must match the immutable batch identity';
ASSERT p_attempt BETWEEN 0 AND 1
  AS 'attempt is outside the bounded Cloud Run retry count';
ASSERT p_manifest_uri IS NOT NULL AND STARTS_WITH(p_manifest_uri, 'gs://')
  AS 'manifest_uri must identify the explicit immutable GCS manifest';
ASSERT p_stage_table_id IS NOT NULL
  AND ENDS_WITH(p_stage_table_id, CONCAT('.staging.week5_events_', SUBSTR(p_batch_id, 1, 16)))
  AS 'stage_table_id does not match the validated batch';
ASSERT p_stage_load_job_id IS NOT NULL AND LENGTH(p_stage_load_job_id) BETWEEN 1 AND 1024
  AS 'stage_load_job_id is required';
ASSERT p_stage_verify_job_id IS NOT NULL AND LENGTH(p_stage_verify_job_id) BETWEEN 1 AND 1024
  AS 'stage_verify_job_id is required';
ASSERT p_publish_job_id IS NOT NULL AND LENGTH(p_publish_job_id) BETWEEN 1 AND 1024
  AS 'publish_job_id is required';
ASSERT p_published_check_job_id IS NOT NULL
  AND LENGTH(p_published_check_job_id) BETWEEN 1 AND 1024
  AS 'published_check_job_id is required';
ASSERT p_fail_before_publish IS NOT NULL
  AS 'fail_before_publish must be supplied as a non-null BOOL';
ASSERT p_lower_seq > 0 AND p_upper_seq >= p_lower_seq
  AS 'sequence bounds must be positive and ordered';
ASSERT p_expected_row_count > 0
  AS 'expected_row_count must be positive';
ASSERT p_fail_after_merge_once IS NOT NULL
  AS 'fail_after_merge_once must be supplied as a non-null BOOL';
ASSERT p_row_value_sha256 IS NOT NULL AND REGEXP_CONTAINS(p_row_value_sha256, r'^[0-9a-f]{64}$')
  AS 'row_value_sha256 must be a lowercase 64-character SHA-256 digest';
ASSERT p_manifest_sha256 IS NOT NULL AND REGEXP_CONTAINS(p_manifest_sha256, r'^[0-9a-f]{64}$')
  AS 'manifest_sha256 must be a lowercase 64-character SHA-256 digest';
ASSERT p_manifest_generation > 0
  AS 'manifest_generation must be a positive object generation';
ASSERT p_object_sha256 IS NOT NULL AND REGEXP_CONTAINS(p_object_sha256, r'^[0-9a-f]{64}$')
  AS 'object_sha256 must be a lowercase 64-character SHA-256 digest';
ASSERT p_object_generation > 0
  AS 'object_generation must be a positive object generation';
ASSERT p_batch_id = LOWER(TO_HEX(SHA256(CAST(CONCAT(
  'dataforge-operational-v1', '|', CAST(p_lower_seq AS STRING), '|',
  CAST(p_upper_seq AS STRING), '|', p_row_value_sha256
) AS BYTES)))) AS 'batch_id does not match the immutable source/range/row-digest identity';

-- A published replay is a read-only no-op and can be recognized even after
-- its disposable staging table has expired.
SET v_already_published = EXISTS (
  SELECT 1
  FROM ops.week5_run_events
  WHERE batch_id = p_batch_id
    AND status = 'PUBLISHED'
);
SET v_should_fail_after_merge = p_fail_after_merge_once AND NOT EXISTS (
  SELECT 1
  FROM ops.week5_run_events
  WHERE batch_id = p_batch_id
    AND status = 'FAILED'
    AND error_code = 'INJECTED_AFTER_SILVER_BEFORE_CHECKPOINT'
);

IF v_already_published THEN
  ASSERT NOT EXISTS (
    SELECT 1
    FROM ops.week5_run_events
    WHERE batch_id = p_batch_id
      AND status = 'PUBLISHED'
      AND (
        lower_seq != p_lower_seq
        OR upper_seq != p_upper_seq
        OR row_value_sha256 != p_row_value_sha256
        OR manifest_sha256 != p_manifest_sha256
        OR manifest_generation != p_manifest_generation
        OR object_sha256 != p_object_sha256
        OR object_generation != p_object_generation
        OR run_mode != p_run_mode
      )
  ) AS 'published batch_id was reused with different immutable metadata';

  SELECT
    'NO_OP' AS publication_status,
    p_batch_id AS batch_id,
    p_run_id AS run_id,
    (SELECT committed_seq
     FROM ops.pipeline_checkpoints
     WHERE source_id = 'dataforge-operational-v1'
     LIMIT 1) AS committed_seq;
ELSE
  -- Snapshot the immutable staging input before opening the transaction.
  -- The runtime separately checks the exact column names and BigQuery types.
  CREATE TEMP TABLE staged_events AS
  SELECT
    change_seq,
    change_id,
    source_table,
    business_key,
    operation,
    source_updated_at,
    business_event_at,
    schema_version,
    payload,
    payload_sha256,
    SAFE.PARSE_JSON(payload) AS payload_json
  FROM {{STAGING_TABLE_ID}};

  SET v_stage_count = (SELECT COUNT(*) FROM staged_events);
  ASSERT v_stage_count = p_expected_row_count
    AS 'staged row count differs from the manifest';
  ASSERT (SELECT COUNT(DISTINCT change_seq) FROM staged_events) = v_stage_count
    AS 'duplicate change_seq in staged events';
  ASSERT (SELECT COUNT(DISTINCT change_id) FROM staged_events) = v_stage_count
    AS 'duplicate change_id in staged events';
  ASSERT (SELECT COUNTIF(
      change_seq < p_lower_seq OR change_seq > p_upper_seq
    ) FROM staged_events) = 0
    AS 'staged sequence falls outside the inclusive manifest bounds';
  ASSERT (SELECT COUNTIF(
      change_seq IS NULL
      OR change_id IS NULL OR LENGTH(change_id) = 0 OR LENGTH(change_id) > 128
      OR source_table IS NULL
      OR business_key IS NULL OR LENGTH(business_key) = 0 OR LENGTH(business_key) > 256
      OR operation IS NULL
      OR source_updated_at IS NULL
      OR business_event_at IS NULL
      OR schema_version IS NULL OR schema_version != '1'
      OR payload IS NULL
      OR payload_json IS NULL OR JSON_TYPE(payload_json) != 'object'
      OR payload_sha256 IS NULL
      OR NOT REGEXP_CONTAINS(payload_sha256, r'^[0-9a-f]{64}$')
      OR LOWER(TO_HEX(SHA256(CAST(payload AS BYTES)))) != payload_sha256
      OR source_table NOT IN ('orders', 'payment_events')
      OR operation NOT IN ('I', 'U', 'D')
    ) FROM staged_events) = 0
    AS 'staged event identity, operation, schema, JSON, or payload digest is invalid';

  -- Validate full post-images and key-only tombstones before any mutation.
  ASSERT (SELECT COUNTIF(
      source_table = 'orders'
      AND (
        JSON_VALUE(payload_json, '$.order_id') IS NULL
        OR JSON_VALUE(payload_json, '$.order_id') != business_key
        OR IF(operation = 'D',
          ARRAY_LENGTH(JSON_KEYS(payload_json)) != 1
            OR COALESCE(JSON_TYPE(JSON_QUERY(payload_json, '$.order_id')), '') != 'string',
          ARRAY_LENGTH(JSON_KEYS(payload_json)) != 6
            OR JSON_VALUE(payload_json, '$.customer_id') IS NULL
            OR JSON_VALUE(payload_json, '$.order_date') IS NULL
            OR JSON_VALUE(payload_json, '$.province_id') IS NULL
            OR JSON_VALUE(payload_json, '$.status') IS NULL
            OR JSON_VALUE(payload_json, '$.order_net_amount') IS NULL
        )
        OR (operation != 'D' AND (
          JSON_TYPE(JSON_QUERY(payload_json, '$.order_id')) != 'string'
          OR JSON_TYPE(JSON_QUERY(payload_json, '$.customer_id')) != 'string'
          OR JSON_TYPE(JSON_QUERY(payload_json, '$.order_date')) != 'string'
          OR JSON_TYPE(JSON_QUERY(payload_json, '$.province_id')) != 'string'
          OR JSON_TYPE(JSON_QUERY(payload_json, '$.status')) != 'string'
          OR JSON_TYPE(JSON_QUERY(payload_json, '$.order_net_amount')) != 'string'
          OR SAFE.PARSE_DATE('%F', JSON_VALUE(payload_json, '$.order_date')) IS NULL
          OR DATE(business_event_at) != SAFE.PARSE_DATE('%F', JSON_VALUE(payload_json, '$.order_date'))
          OR NOT REGEXP_CONTAINS(
            JSON_VALUE(payload_json, '$.order_net_amount'),
            r'^(0|[1-9][0-9]{0,15})\.[0-9]{2}$'
          )
          OR SAFE_CAST(JSON_VALUE(payload_json, '$.order_net_amount') AS NUMERIC) IS NULL
        ))
      )
    ) FROM staged_events) = 0
    AS 'order payload does not match the version-1 post-image/tombstone contract';

  ASSERT (SELECT COUNTIF(
      source_table = 'payment_events'
      AND (
        JSON_VALUE(payload_json, '$.payment_id') IS NULL
        OR JSON_VALUE(payload_json, '$.payment_id') != business_key
        OR IF(operation = 'D',
          ARRAY_LENGTH(JSON_KEYS(payload_json)) != 1
            OR COALESCE(JSON_TYPE(JSON_QUERY(payload_json, '$.payment_id')), '') != 'string',
          ARRAY_LENGTH(JSON_KEYS(payload_json)) != 6
            OR JSON_VALUE(payload_json, '$.order_id') IS NULL
            OR JSON_VALUE(payload_json, '$.payment_date') IS NULL
            OR JSON_VALUE(payload_json, '$.amount') IS NULL
            OR JSON_VALUE(payload_json, '$.status') IS NULL
            OR JSON_VALUE(payload_json, '$.method') IS NULL
        )
        OR (operation != 'D' AND (
          JSON_TYPE(JSON_QUERY(payload_json, '$.payment_id')) != 'string'
          OR JSON_TYPE(JSON_QUERY(payload_json, '$.order_id')) != 'string'
          OR JSON_TYPE(JSON_QUERY(payload_json, '$.payment_date')) != 'string'
          OR JSON_TYPE(JSON_QUERY(payload_json, '$.amount')) != 'string'
          OR JSON_TYPE(JSON_QUERY(payload_json, '$.status')) != 'string'
          OR JSON_TYPE(JSON_QUERY(payload_json, '$.method')) != 'string'
          OR SAFE.PARSE_DATE('%F', JSON_VALUE(payload_json, '$.payment_date')) IS NULL
          OR DATE(business_event_at) != SAFE.PARSE_DATE('%F', JSON_VALUE(payload_json, '$.payment_date'))
          OR NOT REGEXP_CONTAINS(
            JSON_VALUE(payload_json, '$.amount'),
            r'^(0|[1-9][0-9]{0,15})\.[0-9]{2}$'
          )
          OR SAFE_CAST(JSON_VALUE(payload_json, '$.amount') AS NUMERIC) IS NULL
        ))
      )
    ) FROM staged_events) = 0
    AS 'payment payload does not match the version-1 post-image/tombstone contract';

  -- One source row per entity avoids MERGE ambiguity. Highest journal sequence
  -- wins within each entity and source table; event time is never the cursor.
  CREATE TEMP TABLE latest_events AS
  SELECT * EXCEPT (event_rank)
  FROM (
    SELECT
      staged_events.*,
      ROW_NUMBER() OVER (
        PARTITION BY source_table, business_key
        ORDER BY change_seq DESC
      ) AS event_rank
    FROM staged_events
  )
  WHERE event_rank = 1;

  BEGIN
    BEGIN TRANSACTION;

    ASSERT (SELECT COUNT(*) FROM ops.writer_locks
            WHERE lock_name = 'dataforge-operational-v1') = 1
      AS 'writer lock row must exist exactly once';
    UPDATE ops.writer_locks
    SET lock_version = lock_version + 1,
        touched_at = CURRENT_TIMESTAMP(),
        last_run_id = p_run_id
    WHERE lock_name = 'dataforge-operational-v1';
    SET v_lock_rows = @@row_count;
    ASSERT v_lock_rows = 1 AS 'could not acquire the single-writer lock';

    ASSERT (SELECT COUNT(*) FROM ops.pipeline_checkpoints
            WHERE source_id = 'dataforge-operational-v1') = 1
      AS 'checkpoint row must exist exactly once';
    SET v_checkpoint_seq = (
      SELECT committed_seq
      FROM ops.pipeline_checkpoints
      WHERE source_id = 'dataforge-operational-v1'
    );
    IF p_run_mode = 'normal' THEN
      ASSERT p_lower_seq = v_checkpoint_seq + 1
        AS 'normal batch does not begin immediately after the committed checkpoint';
    END IF;

    -- Capture both pre-update and post-image payment order IDs so an update
    -- that moves an event recomputes both affected per-order controls.
    SET v_affected_order_ids = ARRAY(
      SELECT DISTINCT order_id
      FROM (
        SELECT business_key AS order_id
        FROM latest_events
        WHERE source_table = 'orders'
        UNION ALL
        SELECT JSON_VALUE(payload_json, '$.order_id') AS order_id
        FROM latest_events
        WHERE source_table = 'payment_events'
          AND operation IN ('I', 'U')
        UNION ALL
        SELECT current_payment.order_id AS order_id
        FROM latest_events AS event
        JOIN silver.week5_payment_events AS current_payment
          ON event.source_table = 'payment_events'
         AND current_payment.payment_id = event.business_key
        WHERE current_payment.order_id IS NOT NULL
      )
      WHERE order_id IS NOT NULL
      ORDER BY order_id
    );
    SET v_affected_order_count = ARRAY_LENGTH(v_affected_order_ids);

    -- A repeated sequence may be an exact replay of current Silver. It may
    -- not assign another event identity or payload to that same effective seq.
    ASSERT NOT EXISTS (
      SELECT 1
      FROM latest_events AS event
      JOIN silver.week5_orders AS current_order
        ON event.source_table = 'orders'
       AND current_order.order_id = event.business_key
      WHERE event.change_seq = current_order.effective_seq
        AND (
          event.change_id != current_order.last_change_id
          OR event.payload_sha256 != current_order.last_payload_sha256
        )
      UNION ALL
      SELECT 1
      FROM latest_events AS event
      JOIN silver.week5_payment_events AS current_payment
        ON event.source_table = 'payment_events'
       AND current_payment.payment_id = event.business_key
      WHERE event.change_seq = current_payment.effective_seq
        AND (
          event.change_id != current_payment.last_change_id
          OR event.payload_sha256 != current_payment.last_payload_sha256
        )
    ) AS 'effective sequence conflicts with an existing Silver event identity';

    MERGE silver.week5_orders AS target
    USING (
      SELECT *
      FROM latest_events
      WHERE source_table = 'orders'
    ) AS source
    ON target.order_id = source.business_key
    WHEN MATCHED AND source.change_seq > target.effective_seq THEN
      UPDATE SET
        customer_id = IF(source.operation = 'D', target.customer_id,
          JSON_VALUE(source.payload_json, '$.customer_id')),
        order_date = IF(source.operation = 'D', target.order_date,
          SAFE.PARSE_DATE('%F', JSON_VALUE(source.payload_json, '$.order_date'))),
        province_id = IF(source.operation = 'D', target.province_id,
          JSON_VALUE(source.payload_json, '$.province_id')),
        order_status = IF(source.operation = 'D', target.order_status,
          JSON_VALUE(source.payload_json, '$.status')),
        order_net_amount = IF(source.operation = 'D', target.order_net_amount,
          SAFE_CAST(JSON_VALUE(source.payload_json, '$.order_net_amount') AS NUMERIC)),
        is_deleted = source.operation = 'D',
        effective_seq = source.change_seq,
        last_change_id = source.change_id,
        last_payload_sha256 = source.payload_sha256,
        source_updated_at = source.source_updated_at,
        business_event_at = source.business_event_at,
        last_batch_id = p_batch_id,
        ingested_at = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN
      INSERT (
        order_id, customer_id, order_date, province_id, order_status,
        order_net_amount, is_deleted, effective_seq, last_change_id,
        last_payload_sha256, source_updated_at, business_event_at,
        last_batch_id, ingested_at
      )
      VALUES (
        source.business_key,
        IF(source.operation = 'D', NULL, JSON_VALUE(source.payload_json, '$.customer_id')),
        IF(source.operation = 'D', NULL,
          SAFE.PARSE_DATE('%F', JSON_VALUE(source.payload_json, '$.order_date'))),
        IF(source.operation = 'D', NULL, JSON_VALUE(source.payload_json, '$.province_id')),
        IF(source.operation = 'D', NULL, JSON_VALUE(source.payload_json, '$.status')),
        IF(source.operation = 'D', NULL,
          SAFE_CAST(JSON_VALUE(source.payload_json, '$.order_net_amount') AS NUMERIC)),
        source.operation = 'D', source.change_seq, source.change_id,
        source.payload_sha256, source.source_updated_at, source.business_event_at,
        p_batch_id, CURRENT_TIMESTAMP()
      );

    MERGE silver.week5_payment_events AS target
    USING (
      SELECT *
      FROM latest_events
      WHERE source_table = 'payment_events'
    ) AS source
    ON target.payment_id = source.business_key
    WHEN MATCHED AND source.change_seq > target.effective_seq THEN
      UPDATE SET
        order_id = IF(source.operation = 'D', target.order_id,
          JSON_VALUE(source.payload_json, '$.order_id')),
        payment_date = IF(source.operation = 'D', target.payment_date,
          SAFE.PARSE_DATE('%F', JSON_VALUE(source.payload_json, '$.payment_date'))),
        amount = IF(source.operation = 'D', target.amount,
          SAFE_CAST(JSON_VALUE(source.payload_json, '$.amount') AS NUMERIC)),
        payment_status = IF(source.operation = 'D', target.payment_status,
          JSON_VALUE(source.payload_json, '$.status')),
        method = IF(source.operation = 'D', target.method,
          JSON_VALUE(source.payload_json, '$.method')),
        is_deleted = source.operation = 'D',
        effective_seq = source.change_seq,
        last_change_id = source.change_id,
        last_payload_sha256 = source.payload_sha256,
        source_updated_at = source.source_updated_at,
        business_event_at = source.business_event_at,
        last_batch_id = p_batch_id,
        ingested_at = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN
      INSERT (
        payment_id, order_id, payment_date, amount, payment_status, method,
        is_deleted, effective_seq, last_change_id, last_payload_sha256,
        source_updated_at, business_event_at, last_batch_id, ingested_at
      )
      VALUES (
        source.business_key,
        IF(source.operation = 'D', NULL, JSON_VALUE(source.payload_json, '$.order_id')),
        IF(source.operation = 'D', NULL,
          SAFE.PARSE_DATE('%F', JSON_VALUE(source.payload_json, '$.payment_date'))),
        IF(source.operation = 'D', NULL,
          SAFE_CAST(JSON_VALUE(source.payload_json, '$.amount') AS NUMERIC)),
        IF(source.operation = 'D', NULL, JSON_VALUE(source.payload_json, '$.status')),
        IF(source.operation = 'D', NULL, JSON_VALUE(source.payload_json, '$.method')),
        source.operation = 'D', source.change_seq, source.change_id,
        source.payload_sha256, source.source_updated_at, source.business_event_at,
        p_batch_id, CURRENT_TIMESTAMP()
      );

    IF v_should_fail_after_merge THEN
      ASSERT FALSE AS 'INJECTED_AFTER_SILVER_BEFORE_CHECKPOINT';
    END IF;

    INSERT INTO ops.week5_run_events (
      event_id, run_id, execution_id, batch_id, status, run_mode, source_run_id, event_at,
      attempt, manifest_uri, lower_seq, upper_seq, expected_row_count,
      row_value_sha256, manifest_sha256, manifest_generation,
      object_sha256, object_generation, stage_table_id, stage_load_job_id,
      stage_verify_job_id, publish_job_id, checkpoint_before
    )
    VALUES (
      CONCAT(p_run_id, ':MERGED'), p_run_id, p_execution_id, p_batch_id, 'MERGED', p_run_mode,
      p_source_run_id, CURRENT_TIMESTAMP(), p_attempt, p_manifest_uri,
      p_lower_seq, p_upper_seq, p_expected_row_count, p_row_value_sha256,
      p_manifest_sha256, p_manifest_generation, p_object_sha256,
      p_object_generation, p_stage_table_id, p_stage_load_job_id,
      p_stage_verify_job_id, p_publish_job_id, v_checkpoint_seq
    );

    ASSERT NOT EXISTS (
      SELECT 1
      FROM silver.week5_orders
      GROUP BY order_id
      HAVING COUNT(*) > 1
    ) AS 'Silver contains duplicate current order keys';
    ASSERT NOT EXISTS (
      SELECT 1
      FROM silver.week5_payment_events
      GROUP BY payment_id
      HAVING COUNT(*) > 1
    ) AS 'Silver contains duplicate current payment keys';
    ASSERT NOT EXISTS (
      SELECT 1
      FROM silver.week5_payment_events AS payment
      LEFT JOIN silver.week5_orders AS order_row
        ON order_row.order_id = payment.order_id
      WHERE NOT payment.is_deleted
        AND order_row.order_id IS NULL
    ) AS 'active payment references an order missing from Silver';

    MERGE gold.week5_order_controls AS target
    USING (
      WITH affected AS (
        SELECT order_id
        FROM UNNEST(v_affected_order_ids) AS order_id
      ),
      payment_totals AS (
        SELECT
          payment.order_id,
          COUNT(*) AS active_payment_count,
          COUNTIF(payment_status = 'success') AS successful_payment_count,
          SUM(IF(payment_status = 'success', amount, CAST(0 AS NUMERIC)))
            AS collected_amount
        FROM silver.week5_payment_events AS payment
        JOIN affected USING (order_id)
        WHERE NOT payment.is_deleted
        GROUP BY payment.order_id
      )
      SELECT
        order_row.order_id,
        order_row.customer_id,
        order_row.order_date,
        order_row.province_id,
        order_row.order_status,
        order_row.is_deleted AS order_is_deleted,
        IF(
          order_row.is_deleted OR order_row.order_status != 'delivered',
          CAST(0 AS NUMERIC),
          COALESCE(order_row.order_net_amount, CAST(0 AS NUMERIC))
        ) AS delivered_sales_proxy,
        COALESCE(payment_totals.collected_amount, CAST(0 AS NUMERIC))
          AS collected_amount,
        order_row.effective_seq AS order_effective_seq,
        COALESCE(payment_totals.active_payment_count, 0) AS active_payment_count,
        COALESCE(payment_totals.successful_payment_count, 0) AS successful_payment_count
      FROM affected
      JOIN silver.week5_orders AS order_row USING (order_id)
      LEFT JOIN payment_totals USING (order_id)
    ) AS source
    ON target.order_id = source.order_id
    WHEN MATCHED THEN
      UPDATE SET
        customer_id = source.customer_id,
        order_date = source.order_date,
        province_id = source.province_id,
        order_status = source.order_status,
        order_is_deleted = source.order_is_deleted,
        delivered_sales_proxy = source.delivered_sales_proxy,
        collected_amount = source.collected_amount,
        collection_variance = IF(source.order_is_deleted, NULL,
          source.collected_amount - source.delivered_sales_proxy),
        active_payment_count = source.active_payment_count,
        successful_payment_count = source.successful_payment_count,
        order_effective_seq = source.order_effective_seq,
        published_batch_id = p_batch_id,
        published_run_id = p_run_id,
        updated_at = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN
      INSERT (
        order_id, customer_id, order_date, province_id, order_status,
        order_is_deleted, delivered_sales_proxy, collected_amount,
        collection_variance, active_payment_count, successful_payment_count,
        order_effective_seq, published_batch_id, published_run_id, updated_at
      )
      VALUES (
        source.order_id, source.customer_id, source.order_date,
        source.province_id, source.order_status, source.order_is_deleted,
        source.delivered_sales_proxy, source.collected_amount,
        IF(source.order_is_deleted, NULL,
          source.collected_amount - source.delivered_sales_proxy),
        source.active_payment_count, source.successful_payment_count,
        source.order_effective_seq, p_batch_id, p_run_id, CURRENT_TIMESTAMP()
      );

    ASSERT NOT EXISTS (
      SELECT 1
      FROM gold.week5_order_controls
      GROUP BY order_id
      HAVING COUNT(*) > 1
    ) AS 'Gold contains duplicate per-order control keys';
    ASSERT NOT EXISTS (
      SELECT order_id
      FROM UNNEST(v_affected_order_ids) AS order_id
      JOIN silver.week5_orders USING (order_id)
      EXCEPT DISTINCT
      SELECT order_id
      FROM gold.week5_order_controls
    ) AS 'an affected Silver order is missing from Gold';

    SET v_affected_delivered_sales_proxy = COALESCE((
      SELECT SUM(delivered_sales_proxy)
      FROM gold.week5_order_controls
      WHERE order_id IN UNNEST(v_affected_order_ids)
    ), CAST(0 AS NUMERIC));
    SET v_affected_collected_amount = COALESCE((
      SELECT SUM(collected_amount)
      FROM gold.week5_order_controls
      WHERE order_id IN UNNEST(v_affected_order_ids)
    ), CAST(0 AS NUMERIC));

    INSERT INTO ops.week5_run_events (
      event_id, run_id, execution_id, batch_id, status, run_mode, source_run_id, event_at,
      attempt, manifest_uri, lower_seq, upper_seq, expected_row_count,
      row_value_sha256, manifest_sha256, manifest_generation,
      object_sha256, object_generation, stage_table_id, stage_load_job_id,
      stage_verify_job_id, publish_job_id, affected_order_count,
      delivered_sales_proxy, collected_amount, checkpoint_before
    )
    VALUES (
      CONCAT(p_run_id, ':CHECKED'), p_run_id, p_execution_id, p_batch_id, 'CHECKED', p_run_mode,
      p_source_run_id, TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 1 MICROSECOND),
      p_attempt, p_manifest_uri,
      p_lower_seq, p_upper_seq, p_expected_row_count, p_row_value_sha256,
      p_manifest_sha256, p_manifest_generation, p_object_sha256,
      p_object_generation, p_stage_table_id, p_stage_load_job_id,
      p_stage_verify_job_id, p_publish_job_id, v_affected_order_count,
      v_affected_delivered_sales_proxy, v_affected_collected_amount, v_checkpoint_seq
    );

    IF p_fail_before_publish THEN
      ASSERT FALSE AS 'INJECTED_BEFORE_PUBLISH';
    END IF;

    IF p_run_mode = 'normal' THEN
      UPDATE ops.pipeline_checkpoints
      SET committed_seq = p_upper_seq,
          last_batch_id = p_batch_id,
          row_value_sha256 = p_row_value_sha256,
          manifest_sha256 = p_manifest_sha256,
          manifest_generation = p_manifest_generation,
          object_sha256 = p_object_sha256,
          object_generation = p_object_generation,
          updated_at = CURRENT_TIMESTAMP()
      WHERE source_id = 'dataforge-operational-v1';
      SET v_checkpoint_rows = @@row_count;
      ASSERT v_checkpoint_rows = 1 AS 'checkpoint update did not target exactly one row';
    END IF;
    SET v_checkpoint_after = IF(p_run_mode = 'normal', p_upper_seq, v_checkpoint_seq);

    INSERT INTO ops.week5_run_events (
      event_id, run_id, execution_id, batch_id, status, run_mode, event_at,
      source_run_id, attempt, manifest_uri,
      lower_seq, upper_seq, expected_row_count, row_value_sha256,
      manifest_sha256, manifest_generation, object_sha256, object_generation,
      stage_table_id, stage_load_job_id, stage_verify_job_id, publish_job_id,
      published_check_job_id,
      checkpoint_before, checkpoint_after,
      affected_order_count, delivered_sales_proxy, collected_amount,
      error_code, error_message
    )
    VALUES (
      CONCAT(p_run_id, ':PUBLISHED'),
      p_run_id, p_execution_id, p_batch_id, 'PUBLISHED', p_run_mode,
      TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 2 MICROSECOND),
      p_source_run_id, p_attempt, p_manifest_uri,
      p_lower_seq, p_upper_seq, p_expected_row_count, p_row_value_sha256,
      p_manifest_sha256, p_manifest_generation, p_object_sha256, p_object_generation,
      p_stage_table_id, p_stage_load_job_id, p_stage_verify_job_id, p_publish_job_id,
      p_published_check_job_id,
      v_checkpoint_seq, v_checkpoint_after,
      v_affected_order_count, v_affected_delivered_sales_proxy,
      v_affected_collected_amount, NULL, NULL
    );

    COMMIT TRANSACTION;
  EXCEPTION WHEN ERROR THEN
    ROLLBACK TRANSACTION;
    INSERT INTO ops.week5_run_events (
      event_id, run_id, execution_id, batch_id, status, run_mode, event_at,
      source_run_id, attempt, manifest_uri,
      lower_seq, upper_seq, expected_row_count, row_value_sha256,
      manifest_sha256, manifest_generation, object_sha256, object_generation,
      stage_table_id, stage_load_job_id, stage_verify_job_id, publish_job_id,
      published_check_job_id,
      checkpoint_before, checkpoint_after, error_code, error_message
    )
    VALUES (
      CONCAT(p_run_id, ':FAILED'),
      p_run_id, p_execution_id, p_batch_id, 'FAILED', p_run_mode, CURRENT_TIMESTAMP(),
      p_source_run_id, p_attempt, p_manifest_uri,
      p_lower_seq, p_upper_seq, p_expected_row_count, p_row_value_sha256,
      p_manifest_sha256, p_manifest_generation, p_object_sha256, p_object_generation,
      p_stage_table_id, p_stage_load_job_id, p_stage_verify_job_id, p_publish_job_id,
      NULL,
      v_checkpoint_seq, v_checkpoint_after,
      IF(STRPOS(@@error.message, 'INJECTED_AFTER_SILVER_BEFORE_CHECKPOINT') > 0,
        'INJECTED_AFTER_SILVER_BEFORE_CHECKPOINT',
        IF(STRPOS(@@error.message, 'INJECTED_BEFORE_PUBLISH') > 0,
          'INJECTED_BEFORE_PUBLISH',
          'BQ_TRANSACTION_FAILED')),
      IF(STRPOS(@@error.message, 'INJECTED_AFTER_SILVER_BEFORE_CHECKPOINT') > 0,
        'Injected after Silver MERGE before checkpoint; transaction rolled back.',
        IF(STRPOS(@@error.message, 'INJECTED_BEFORE_PUBLISH') > 0,
          'Injected before publish; transaction rolled back.',
          'BigQuery publication transaction failed; inspect the recorded job receipt.'))
    );
    RAISE;
  END;

  SELECT
    'PUBLISHED' AS publication_status,
    p_batch_id AS batch_id,
    p_run_id AS run_id,
    v_checkpoint_after AS committed_seq,
    v_affected_order_count AS affected_order_count,
    v_affected_delivered_sales_proxy AS affected_delivered_sales_proxy,
    v_affected_collected_amount AS affected_collected_amount;
END IF;
