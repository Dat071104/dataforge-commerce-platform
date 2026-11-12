{% macro _week7_validate_workflow_run_id(value) %}
    {% if value is not string or value | length < 1 or value | length > 128 %}
        {{ exceptions.raise_compiler_error('workflow_run_id must be a 1-128 character string') }}
    {% endif %}
    {% set allowed = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' %}
    {% for character in value %}
        {% if character not in allowed %}
            {{ exceptions.raise_compiler_error('workflow_run_id may contain only letters, digits, underscore, and hyphen') }}
        {% endif %}
    {% endfor %}
{% endmacro %}

{% macro _week7_validate_publication_args(batch_id, manifest_generation, upper_seq, workflow_run_id) %}
    {% do _week7_validate_workflow_run_id(workflow_run_id) %}
    {% if batch_id is not string or batch_id | length != 64 %}
        {{ exceptions.raise_compiler_error('batch_id must be a 64-character lowercase SHA-256 digest') }}
    {% endif %}
    {% set hexchars = '0123456789abcdef' %}
    {% for character in batch_id %}
        {% if character not in hexchars %}
            {{ exceptions.raise_compiler_error('batch_id must be lowercase hexadecimal') }}
        {% endif %}
    {% endfor %}
    {% if manifest_generation | int <= 0 %}
        {{ exceptions.raise_compiler_error('manifest_generation must be a positive integer') }}
    {% endif %}
    {% if upper_seq | int <= 0 %}
        {{ exceptions.raise_compiler_error('upper_seq must be a positive integer') }}
    {% endif %}
{% endmacro %}

{% macro acquire_week7_lock(
    workflow_run_id,
    lease_seconds=1800,
    batch_id=none,
    manifest_generation=none,
    upper_seq=none,
    run_mode='normal'
) %}
    {% do _week7_validate_workflow_run_id(workflow_run_id) %}
    {% if run_mode not in ['normal', 'backfill'] %}
        {{ exceptions.raise_compiler_error('run_mode must be normal or backfill') }}
    {% endif %}
    {% set lease_seconds = lease_seconds | int %}
    {% if lease_seconds < 60 or lease_seconds > 3600 %}
        {{ exceptions.raise_compiler_error('lease_seconds must be between 60 and 3600') }}
    {% endif %}
    {% if batch_id is not none or manifest_generation is not none or upper_seq is not none %}
        {% if batch_id is none or manifest_generation is none or upper_seq is none %}
            {{ exceptions.raise_compiler_error('batch_id, manifest_generation, and upper_seq must be supplied together') }}
        {% endif %}
        {% do _week7_validate_publication_args(batch_id, manifest_generation, upper_seq, workflow_run_id) %}
        {% set p_batch_id = "'" ~ batch_id ~ "'" %}
        {% set p_manifest_generation = manifest_generation | int %}
        {% set p_upper_seq = upper_seq | int %}
    {% else %}
        {% set p_batch_id = 'NULL' %}
        {% set p_manifest_generation = 'NULL' %}
        {% set p_upper_seq = 'NULL' %}
    {% endif %}
    {% set project = target.database %}
    {% set lock_table = '`' ~ project ~ '.ops.week7_publish_lock`' %}
    {% set events_table = '`' ~ project ~ '.ops.week7_publish_events`' %}
    {% set gold_dataset = env_var('DBT_DATAFORGE_GOLD_DATASET', 'gold_week7') %}
    {% set pointer_table = '`' ~ project ~ '.' ~ gold_dataset ~ '.week7_publication_pointer`' %}
    {% set sql %}
        DECLARE p_batch_id STRING DEFAULT {{ p_batch_id }};
        DECLARE p_manifest_generation INT64 DEFAULT {{ p_manifest_generation }};
        DECLARE p_upper_seq INT64 DEFAULT {{ p_upper_seq }};
        DECLARE p_run_mode STRING DEFAULT '{{ run_mode }}';
        DECLARE v_updated_rows INT64 DEFAULT 0;
        DECLARE v_status STRING DEFAULT 'OVERLAP_SKIPPED';
        DECLARE v_lock_version INT64 DEFAULT NULL;
        DECLARE v_pointer_version INT64 DEFAULT NULL;

        ASSERT (
            SELECT COUNT(*)
            FROM {{ lock_table }}
            WHERE lock_name = 'week7-dbt-publication'
        ) = 1 AS 'Week-7 lock singleton must be provisioned and seeded exactly once';

        BEGIN TRANSACTION;
        UPDATE {{ lock_table }}
        SET lock_owner = '{{ workflow_run_id }}',
            lock_expires_at = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL {{ lease_seconds }} SECOND),
            lock_version = lock_version + 1,
            updated_at = CURRENT_TIMESTAMP()
        WHERE lock_name = 'week7-dbt-publication'
          AND (
              lock_owner IS NULL
              OR lock_expires_at IS NULL
              OR lock_expires_at <= CURRENT_TIMESTAMP()
              OR lock_owner = '{{ workflow_run_id }}'
          );
        SET v_updated_rows = @@row_count;
        ASSERT v_updated_rows IN (0, 1) AS 'Week-7 lock row is not unique';
        SET v_status = IF(v_updated_rows = 1, 'ACQUIRED', 'OVERLAP_SKIPPED');
        SET v_lock_version = (
            SELECT lock_version
            FROM {{ lock_table }}
            WHERE lock_name = 'week7-dbt-publication'
        );
        SET v_pointer_version = (
            SELECT pointer_version
            FROM {{ pointer_table }}
            WHERE pointer_name = 'current_order_reconciliation'
        );
        IF v_updated_rows = 1 THEN
            UPDATE {{ pointer_table }}
            SET publication_is_current = FALSE
            WHERE pointer_name = 'current_order_reconciliation';
            ASSERT @@row_count = 1
              AS 'Week-7 pointer currentness fence could not be set before Silver processing';
        END IF;

        INSERT INTO {{ events_table }} (
            event_id, workflow_run_id, status, event_at, batch_id, run_mode,
            manifest_generation, upper_seq, candidate_dataset, pointer_version, message
        )
        VALUES (
            GENERATE_UUID(), '{{ workflow_run_id }}', v_status, CURRENT_TIMESTAMP(),
            p_batch_id, p_run_mode, p_manifest_generation, p_upper_seq, '{{ target.schema }}', v_pointer_version,
            IF(v_status = 'ACQUIRED', 'Exclusive publication lease acquired.',
                'Another unexpired workflow owns the publication lease.')
        );
        COMMIT TRANSACTION;

        SELECT
            v_status AS status,
            '{{ workflow_run_id }}' AS workflow_run_id,
            v_lock_version AS lock_version,
            FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%E6SZ', (
                SELECT lock_expires_at
                FROM {{ lock_table }}
                WHERE lock_name = 'week7-dbt-publication'
            )) AS lock_expires_at;
    {% endset %}
    {% set result = run_query(sql) %}
    {% if result is not none and result.rows | length > 0 %}
        {% do log(
            'DATAFORGE_WEEK7_RESULT status=' ~ result.rows[0][0]
            ~ ' workflow_run_id=' ~ result.rows[0][1]
            ~ ' lock_version=' ~ result.rows[0][2],
            info=True
        ) %}
    {% endif %}
{% endmacro %}

{% macro release_week7_lock(workflow_run_id) %}
    {% do _week7_validate_workflow_run_id(workflow_run_id) %}
    {% set project = target.database %}
    {% set lock_table = '`' ~ project ~ '.ops.week7_publish_lock`' %}
    {% set events_table = '`' ~ project ~ '.ops.week7_publish_events`' %}
    {% set gold_dataset = env_var('DBT_DATAFORGE_GOLD_DATASET', 'gold_week7') %}
    {% set pointer_table = '`' ~ project ~ '.' ~ gold_dataset ~ '.week7_publication_pointer`' %}
    {% set sql %}
        DECLARE v_updated_rows INT64 DEFAULT 0;
        DECLARE v_status STRING DEFAULT 'NOT_OWNER';
        DECLARE v_lock_version INT64 DEFAULT NULL;
        DECLARE v_pointer_version INT64 DEFAULT NULL;

        ASSERT (
            SELECT COUNT(*)
            FROM {{ lock_table }}
            WHERE lock_name = 'week7-dbt-publication'
        ) = 1 AS 'Week-7 lock singleton must be provisioned and seeded exactly once';

        BEGIN TRANSACTION;
        UPDATE {{ lock_table }}
        SET lock_owner = NULL,
            lock_expires_at = NULL,
            lock_version = lock_version + 1,
            updated_at = CURRENT_TIMESTAMP()
        WHERE lock_name = 'week7-dbt-publication'
          AND lock_owner = '{{ workflow_run_id }}';
        SET v_updated_rows = @@row_count;
        ASSERT v_updated_rows IN (0, 1) AS 'Week-7 lock row is not unique';
        SET v_status = IF(v_updated_rows = 1, 'RELEASED', 'NOT_OWNER');
        SET v_lock_version = (
            SELECT lock_version
            FROM {{ lock_table }}
            WHERE lock_name = 'week7-dbt-publication'
        );
        SET v_pointer_version = (
            SELECT pointer_version
            FROM {{ pointer_table }}
            WHERE pointer_name = 'current_order_reconciliation'
        );

        INSERT INTO {{ events_table }} (
            event_id, workflow_run_id, status, event_at, candidate_dataset,
            pointer_version, message
        )
        VALUES (
            GENERATE_UUID(), '{{ workflow_run_id }}', v_status, CURRENT_TIMESTAMP(),
            '{{ target.schema }}', v_pointer_version,
            IF(v_status = 'RELEASED', 'Exclusive publication lease released.',
                'Release skipped because the workflow no longer owns the lease.')
        );
        COMMIT TRANSACTION;

        SELECT v_status AS status, '{{ workflow_run_id }}' AS workflow_run_id,
            v_lock_version AS lock_version;
    {% endset %}
    {% set result = run_query(sql) %}
    {% if result is not none and result.rows | length > 0 %}
        {% do log(
            'DATAFORGE_WEEK7_RESULT status=' ~ result.rows[0][0]
            ~ ' workflow_run_id=' ~ result.rows[0][1]
            ~ ' lock_version=' ~ result.rows[0][2],
            info=True
        ) %}
    {% endif %}
{% endmacro %}

{% macro publish_week7(
    batch_id,
    manifest_generation,
    upper_seq,
    workflow_run_id,
    run_mode,
    test_fail_before_publish=false
) %}
    {% do _week7_validate_publication_args(batch_id, manifest_generation, upper_seq, workflow_run_id) %}
    {% if run_mode not in ['normal', 'backfill'] %}
        {{ exceptions.raise_compiler_error('run_mode must be normal or backfill') }}
    {% endif %}
    {% if test_fail_before_publish is not boolean %}
        {{ exceptions.raise_compiler_error('test_fail_before_publish must be a boolean') }}
    {% endif %}
    {% if target.schema != 'dbt_week7' %}
        {{ exceptions.raise_compiler_error('publish_week7 is restricted to the incremental dbt_week7 candidate dataset') }}
    {% endif %}

    {% set project = target.database %}
    {% set candidate = '`' ~ project ~ '.' ~ target.schema ~ '.fct_week7_order_reconciliation`' %}
    {% set receipt = '`' ~ project ~ '.' ~ target.schema ~ '.fct_week7_build_receipt`' %}
    {% set batch_control = '`' ~ project ~ '.' ~ target.schema ~ '.int_week7_batch_control`' %}
    {% set delivered = '`' ~ project ~ '.' ~ target.schema ~ '.int_week5_delivered_sales_proxy_by_order`' %}
    {% set payment_control = '`' ~ project ~ '.' ~ target.schema ~ '.int_week5_payment_control_by_order`' %}
    {% set orders_source = '`' ~ project ~ '.' ~ target.schema ~ '.stg_week5_orders`' %}
    {% set payments_source = '`' ~ project ~ '.' ~ target.schema ~ '.stg_week5_payment_events`' %}
    {% set checkpoints = '`' ~ project ~ '.' ~ target.schema ~ '.stg_week5_pipeline_checkpoints`' %}
    {% set lock_table = '`' ~ project ~ '.ops.week7_publish_lock`' %}
    {% set events_table = '`' ~ project ~ '.ops.week7_publish_events`' %}
    {% set gold_dataset = env_var('DBT_DATAFORGE_GOLD_DATASET', 'gold_week7') %}
    {% set pointer_table = '`' ~ project ~ '.' ~ gold_dataset ~ '.week7_publication_pointer`' %}
    {% set versions_table = '`' ~ project ~ '.' ~ gold_dataset ~ '.week7_order_reconciliation_versions`' %}
    {% set published_view = '`' ~ project ~ '.' ~ gold_dataset ~ '.published_order_reconciliation`' %}
    {% set p_test_fail_before_publish = 'TRUE' if test_fail_before_publish else 'FALSE' %}

    {% set create_versions_sql %}
        CREATE TABLE IF NOT EXISTS {{ versions_table }}
        PARTITION BY DATE(published_at)
        CLUSTER BY publication_id, order_id
        AS
        SELECT
            CAST(NULL AS STRING) AS publication_id,
            CAST(NULL AS STRING) AS workflow_run_id,
            CAST(NULL AS STRING) AS batch_id,
            CAST(NULL AS STRING) AS run_mode,
            CAST(NULL AS INT64) AS manifest_generation,
            CAST(NULL AS INT64) AS upper_seq,
            CAST(NULL AS INT64) AS source_checkpoint_seq,
            CAST(NULL AS STRING) AS candidate_dataset,
            CAST(NULL AS INT64) AS candidate_row_count,
            CAST(NULL AS STRING) AS candidate_sha256,
            CAST(NULL AS TIMESTAMP) AS published_at,
            candidate_rows.*
        FROM {{ candidate }} AS candidate_rows
        WHERE FALSE
    {% endset %}
    {% do run_query(create_versions_sql) %}
    {% set create_published_view_sql %}
        CREATE OR REPLACE VIEW {{ published_view }} AS
        SELECT version.*, TRUE AS publication_is_current
        FROM {{ versions_table }} AS version
        JOIN {{ pointer_table }} AS pointer
          ON pointer.pointer_name = 'current_order_reconciliation'
         AND pointer.publication_id = version.publication_id
        WHERE pointer.publication_is_current IS TRUE
    {% endset %}
    {% do run_query(create_published_view_sql) %}

    {% set sql %}
        DECLARE p_batch_id STRING DEFAULT '{{ batch_id }}';
        DECLARE p_workflow_run_id STRING DEFAULT '{{ workflow_run_id }}';
        DECLARE p_manifest_generation INT64 DEFAULT {{ manifest_generation | int }};
        DECLARE p_upper_seq INT64 DEFAULT {{ upper_seq | int }};
        DECLARE p_run_mode STRING DEFAULT '{{ run_mode }}';
        DECLARE p_test_fail_before_publish BOOL DEFAULT {{ p_test_fail_before_publish }};
        DECLARE v_transaction_started BOOL DEFAULT FALSE;
        DECLARE v_failpoint_triggered BOOL DEFAULT FALSE;
        DECLARE v_receipt_count INT64 DEFAULT 0;
        DECLARE v_control_count INT64 DEFAULT 0;
        DECLARE v_backfill_control_count INT64 DEFAULT 0;
        DECLARE v_lock_rows INT64 DEFAULT 0;
        DECLARE v_candidate_count INT64 DEFAULT 0;
        DECLARE v_candidate_sha256 STRING DEFAULT NULL;
        DECLARE v_receipt_sha256 STRING DEFAULT NULL;
        DECLARE v_receipt_run_mode STRING DEFAULT NULL;
        DECLARE v_candidate_checkpoint INT64 DEFAULT NULL;
        DECLARE v_bad_rows INT64 DEFAULT 0;
        DECLARE v_pointer_rows INT64 DEFAULT 0;
        DECLARE v_prior_pointer_version INT64 DEFAULT NULL;
        DECLARE v_prior_upper_seq INT64 DEFAULT NULL;
        DECLARE v_prior_checkpoint_seq INT64 DEFAULT NULL;
        DECLARE v_prior_sha256 STRING DEFAULT NULL;
        DECLARE v_publication_id STRING DEFAULT NULL;
        DECLARE v_existing_version_rows INT64 DEFAULT 0;
        DECLARE v_status STRING DEFAULT 'PUBLISHED';
        DECLARE v_new_pointer_version INT64 DEFAULT NULL;

        BEGIN
        BEGIN TRANSACTION;
        SET v_transaction_started = TRUE;
        ASSERT (
            SELECT COUNT(*)
            FROM {{ lock_table }}
            WHERE lock_name = 'week7-dbt-publication'
        ) = 1 AS 'Week-7 lock singleton must be provisioned and seeded exactly once';
        ASSERT EXISTS (
            SELECT 1
            FROM {{ lock_table }}
            WHERE lock_name = 'week7-dbt-publication'
              AND lock_owner = p_workflow_run_id
              AND lock_expires_at > CURRENT_TIMESTAMP()
        ) AS 'Workflow does not own a current Week-7 publication lease';
        UPDATE {{ lock_table }}
        SET lock_expires_at = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 3600 SECOND),
            lock_version = lock_version + 1,
            updated_at = CURRENT_TIMESTAMP()
        WHERE lock_name = 'week7-dbt-publication'
          AND lock_owner = p_workflow_run_id
          AND lock_expires_at > CURRENT_TIMESTAMP();
        SET v_lock_rows = @@row_count;
        ASSERT v_lock_rows = 1
          AS 'Publication lease expired or changed owner before commit';
        SET v_pointer_rows = (
            SELECT COUNT(*)
            FROM {{ pointer_table }}
            WHERE pointer_name = 'current_order_reconciliation'
        );
        ASSERT v_pointer_rows = 1
          AS 'Week-7 publication pointer singleton must be provisioned and seeded exactly once';

        SET v_receipt_count = (
            SELECT COUNT(*)
            FROM {{ receipt }}
            WHERE workflow_run_id = p_workflow_run_id
        );
        ASSERT v_receipt_count = 1 AS 'Expected exactly one Week-7 build receipt for this workflow_run_id';

        SET (
            v_receipt_sha256,
            v_receipt_run_mode,
            v_candidate_checkpoint
        ) = (
            SELECT AS STRUCT
                ANY_VALUE(candidate_sha256),
                ANY_VALUE(run_mode),
                ANY_VALUE(source_checkpoint_seq)
            FROM {{ receipt }}
            WHERE workflow_run_id = p_workflow_run_id
              AND batch_id = p_batch_id
              AND run_mode = p_run_mode
              AND manifest_generation = p_manifest_generation
              AND upper_seq = p_upper_seq
              AND candidate_project = '{{ target.database }}'
              AND candidate_dataset = '{{ target.schema }}'
        );
        ASSERT v_receipt_sha256 IS NOT NULL AND v_receipt_run_mode = p_run_mode
          AS 'Build receipt does not match this batch, mode, generation, sequence, workflow, and dataset';

        SET v_control_count = (
            SELECT COUNT(*)
            FROM {{ batch_control }}
            WHERE batch_id = p_batch_id
              AND published_manifest_generation = p_manifest_generation
              AND published_upper_seq = p_upper_seq
              AND published_event_count > 0
              AND publish_quality_gate_passed
        );
        ASSERT v_control_count > 0 AS 'The requested batch lacks a verified Week-5 PUBLISHED + CHECKED control';
        SET v_backfill_control_count = (
            SELECT COUNT(*)
            FROM {{ batch_control }}
            WHERE batch_id = p_batch_id
              AND run_mode = 'backfill'
              AND published_manifest_generation = p_manifest_generation
              AND published_upper_seq = p_upper_seq
              AND published_event_count > 0
              AND publish_quality_gate_passed
        );

        ASSERT v_candidate_checkpoint IS NOT NULL
          AND (
              v_candidate_checkpoint >= p_upper_seq
              OR (p_run_mode = 'backfill' AND v_backfill_control_count > 0)
          )
          AS 'Only a checked Week-5 backfill may publish above the normal source checkpoint';

        SET v_candidate_count = (SELECT COUNT(*) FROM {{ candidate }});
        ASSERT v_candidate_count > 0 AS 'The candidate order reconciliation is empty';
        ASSERT v_candidate_count = (SELECT COUNT(*) FROM {{ orders_source }})
          AS 'Candidate order row count differs from current Silver order count';
        ASSERT v_candidate_count = (SELECT COUNT(DISTINCT order_id) FROM {{ candidate }})
          AS 'Candidate contains duplicate order keys';

        SET v_candidate_sha256 = (
            WITH row_hashes AS (
                SELECT
                    order_id,
                    order_id_bucket,
                    TO_HEX(SHA256(CAST(TO_JSON_STRING(STRUCT(
                        order_id, order_id_bucket, customer_id, order_date, province_id,
                        order_status, order_is_deleted, delivered_sales_proxy, collected_amount,
                        collection_variance, active_payment_count, successful_payment_count,
                        order_effective_seq, max_payment_effective_seq,
                        order_ingested_at, latest_payment_ingested_at
                    )) AS BYTES))) AS row_sha256
                FROM {{ candidate }}
            ),
            bucket_hashes AS (
                SELECT
                    order_id_bucket,
                    TO_HEX(SHA256(CAST(STRING_AGG(row_sha256, '|' ORDER BY order_id) AS BYTES)))
                        AS bucket_sha256
                FROM row_hashes
                GROUP BY order_id_bucket
            )
            SELECT TO_HEX(SHA256(CAST(COALESCE(
                STRING_AGG(
                    CONCAT(CAST(order_id_bucket AS STRING), ':', bucket_sha256),
                    '|' ORDER BY order_id_bucket
                ),
                ''
            ) AS BYTES)))
            FROM bucket_hashes
        );
        ASSERT v_candidate_sha256 = v_receipt_sha256
          AS 'Candidate changed after the dbt build receipt was written';

        SET v_bad_rows = (
            WITH expected AS (
                SELECT
                    expected_order.order_id,
                    expected_order.customer_id,
                    expected_order.order_date,
                    expected_order.province_id,
                    expected_order.order_status,
                    expected_order.order_is_deleted,
                    expected_order.delivered_sales_proxy,
                    COALESCE(payments.collected_amount, CAST(0 AS NUMERIC)) AS collected_amount,
                    IF(
                        expected_order.order_is_deleted,
                        CAST(NULL AS NUMERIC),
                        COALESCE(payments.collected_amount, CAST(0 AS NUMERIC))
                            - expected_order.delivered_sales_proxy
                    ) AS collection_variance,
                    COALESCE(payments.active_payment_count, 0) AS active_payment_count,
                    COALESCE(payments.successful_payment_count, 0) AS successful_payment_count,
                    expected_order.order_effective_seq,
                    COALESCE(payments.max_payment_effective_seq, 0) AS max_payment_effective_seq,
                    MOD(MOD(FARM_FINGERPRINT(expected_order.order_id), 64) + 64, 64)
                        AS order_id_bucket
                FROM {{ delivered }} AS expected_order
                LEFT JOIN {{ payment_control }} AS payments USING (order_id)
            ),
            actual AS (
                SELECT
                    order_id,
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
                    order_id_bucket
                FROM {{ candidate }}
            )
            SELECT COUNT(*)
            FROM expected
            FULL OUTER JOIN actual
                ON expected.order_id = actual.order_id
            WHERE expected.order_id IS NULL
                OR actual.order_id IS NULL
                OR expected.customer_id IS DISTINCT FROM actual.customer_id
                OR expected.order_date IS DISTINCT FROM actual.order_date
                OR expected.province_id IS DISTINCT FROM actual.province_id
                OR expected.order_status IS DISTINCT FROM actual.order_status
                OR expected.order_is_deleted IS DISTINCT FROM actual.order_is_deleted
                OR expected.delivered_sales_proxy IS DISTINCT FROM actual.delivered_sales_proxy
                OR expected.collected_amount IS DISTINCT FROM actual.collected_amount
                OR expected.collection_variance IS DISTINCT FROM actual.collection_variance
                OR expected.active_payment_count IS DISTINCT FROM actual.active_payment_count
                OR expected.successful_payment_count IS DISTINCT FROM actual.successful_payment_count
                OR expected.order_effective_seq IS DISTINCT FROM actual.order_effective_seq
                OR expected.max_payment_effective_seq IS DISTINCT FROM actual.max_payment_effective_seq
                OR expected.order_id_bucket IS DISTINCT FROM actual.order_id_bucket
        );
        ASSERT v_bad_rows = 0 AS 'Candidate differs from the current Silver-derived order reconciliation';

        SET v_publication_id = TO_HEX(SHA256(CAST(CONCAT(
            p_batch_id, '|', CAST(p_manifest_generation AS STRING), '|',
            CAST(p_upper_seq AS STRING), '|', p_run_mode, '|',
            CAST(v_candidate_checkpoint AS STRING), '|', v_candidate_sha256
        ) AS BYTES)));
        IF p_test_fail_before_publish THEN
            SET v_failpoint_triggered = TRUE;
            ASSERT FALSE AS 'INJECTED_FAIL_BEFORE_PUBLISH';
        END IF;

        SET v_prior_pointer_version = (
            SELECT pointer_version
            FROM {{ pointer_table }}
            WHERE pointer_name = 'current_order_reconciliation'
        );
        SET v_prior_upper_seq = (
            SELECT upper_seq
            FROM {{ pointer_table }}
            WHERE pointer_name = 'current_order_reconciliation'
        );
        SET v_prior_checkpoint_seq = (
            SELECT source_checkpoint_seq
            FROM {{ pointer_table }}
            WHERE pointer_name = 'current_order_reconciliation'
        );
        SET v_prior_sha256 = (
            SELECT candidate_sha256
            FROM {{ pointer_table }}
            WHERE pointer_name = 'current_order_reconciliation'
        );
        SET v_existing_version_rows = (
            SELECT COUNT(*)
            FROM {{ versions_table }}
            WHERE publication_id = v_publication_id
        );
        ASSERT v_existing_version_rows IN (0, v_candidate_count)
          AS 'Existing immutable publication version has an unexpected row count';
        ASSERT (
            SELECT COUNTIF(
                batch_id != p_batch_id
                OR manifest_generation != p_manifest_generation
                OR upper_seq != p_upper_seq
                OR run_mode != p_run_mode
                OR candidate_row_count != v_candidate_count
                OR candidate_sha256 != v_candidate_sha256
            )
            FROM {{ versions_table }}
            WHERE publication_id = v_publication_id
        ) = 0 AS 'Publication ID was reused with different immutable metadata';

        IF v_prior_pointer_version > 0
           AND v_candidate_checkpoint = v_prior_checkpoint_seq
           AND v_candidate_sha256 = v_prior_sha256 THEN
            UPDATE {{ pointer_table }}
            SET publication_is_current = TRUE
            WHERE pointer_name = 'current_order_reconciliation'
              AND pointer_version = v_prior_pointer_version;
            ASSERT @@row_count = 1
              AS 'Idempotent validated replay could not restore the current publication marker';
            SET v_status = 'NO_OP';
            SET v_new_pointer_version = v_prior_pointer_version;
        ELSE
            ASSERT v_prior_pointer_version = 0
                OR v_candidate_checkpoint >= v_prior_checkpoint_seq
              AS 'The published source checkpoint cannot move backwards';
            ASSERT v_prior_pointer_version = 0
                OR v_candidate_checkpoint > v_prior_checkpoint_seq
                OR p_run_mode = 'backfill'
              AS 'A same-checkpoint snapshot correction requires a checked backfill';
            IF v_existing_version_rows = 0 THEN
                INSERT INTO {{ versions_table }} (
                    publication_id, workflow_run_id, batch_id, run_mode, manifest_generation,
                    upper_seq, source_checkpoint_seq, candidate_dataset,
                    candidate_row_count, candidate_sha256, published_at,
                    order_id, order_id_bucket, customer_id, order_date, province_id,
                    order_status, order_is_deleted, delivered_sales_proxy, collected_amount,
                    collection_variance, active_payment_count, successful_payment_count,
                    order_effective_seq, max_payment_effective_seq,
                    order_ingested_at, latest_payment_ingested_at
                )
                SELECT
                    v_publication_id,
                    p_workflow_run_id,
                    p_batch_id,
                    p_run_mode,
                    p_manifest_generation,
                    p_upper_seq,
                    v_candidate_checkpoint,
                    '{{ target.schema }}',
                    v_candidate_count,
                    v_candidate_sha256,
                    CURRENT_TIMESTAMP(),
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
                FROM {{ candidate }};
            ELSE
                ASSERT (
                    SELECT COUNTIF(
                        candidate_sha256 != v_candidate_sha256
                        OR batch_id != p_batch_id
                        OR run_mode != p_run_mode
                        OR manifest_generation != p_manifest_generation
                        OR upper_seq != p_upper_seq
                        OR candidate_row_count != v_candidate_count
                    )
                    FROM {{ versions_table }}
                    WHERE publication_id = v_publication_id
                ) = 0 AS 'Idempotent publication replay does not match the immutable run-version';
            END IF;

            UPDATE {{ pointer_table }}
            SET published_run_id = p_workflow_run_id,
                batch_id = p_batch_id,
                published_run_mode = p_run_mode,
                manifest_generation = p_manifest_generation,
                upper_seq = p_upper_seq,
                publication_id = v_publication_id,
                source_checkpoint_seq = v_candidate_checkpoint,
                candidate_dataset = '{{ target.schema }}',
                candidate_row_count = v_candidate_count,
                candidate_sha256 = v_candidate_sha256,
                publication_is_current = TRUE,
                pointer_version = pointer_version + 1,
                published_at = CURRENT_TIMESTAMP()
            WHERE pointer_name = 'current_order_reconciliation'
              AND pointer_version = v_prior_pointer_version;
            ASSERT @@row_count = 1 AS 'Week-7 pointer compare-and-set failed';
            SET v_new_pointer_version = v_prior_pointer_version + 1;
            SET v_status = 'PUBLISHED';
        END IF;

        INSERT INTO {{ events_table }} (
            event_id, workflow_run_id, status, event_at, batch_id, run_mode,
            manifest_generation, upper_seq, source_checkpoint_seq, publication_id,
            candidate_dataset, candidate_row_count, candidate_sha256,
            pointer_version, message
        )
        VALUES (
            GENERATE_UUID(), p_workflow_run_id, v_status, CURRENT_TIMESTAMP(), p_batch_id, p_run_mode,
            p_manifest_generation, p_upper_seq, v_candidate_checkpoint, v_publication_id,
            '{{ target.schema }}', v_candidate_count, v_candidate_sha256,
            v_new_pointer_version,
            IF(v_status = 'PUBLISHED', 'Immutable run-version committed and pointer advanced.',
                'Candidate matched the already published sequence or immutable version.')
        );
        COMMIT TRANSACTION;
        SET v_transaction_started = FALSE;
        EXCEPTION WHEN ERROR THEN
            IF v_transaction_started THEN
                ROLLBACK TRANSACTION;
            END IF;
            INSERT INTO {{ events_table }} (
                event_id, workflow_run_id, status, event_at, batch_id, run_mode,
                manifest_generation, upper_seq, source_checkpoint_seq, publication_id,
                candidate_dataset, candidate_row_count, candidate_sha256,
                pointer_version, message
            )
            VALUES (
                GENERATE_UUID(), p_workflow_run_id,
                IF(v_failpoint_triggered, 'INJECTED_FAILURE', 'FAILED'),
                CURRENT_TIMESTAMP(), p_batch_id, p_run_mode,
                p_manifest_generation, p_upper_seq, v_candidate_checkpoint, v_publication_id,
                '{{ target.schema }}', v_candidate_count, v_candidate_sha256,
                (SELECT pointer_version FROM {{ pointer_table }}
                 WHERE pointer_name = 'current_order_reconciliation'),
                IF(
                    v_failpoint_triggered,
                    'Controlled Week-7 failure drill; candidate validated; publish transaction rolled back.',
                    'Week-7 publication failed; details redacted; inspect the workflow run.'
                )
            );
            RAISE;
        END;

        SELECT
            v_status AS status,
            p_workflow_run_id AS workflow_run_id,
            p_batch_id AS batch_id,
            p_manifest_generation AS manifest_generation,
            p_upper_seq AS upper_seq,
            v_candidate_checkpoint AS source_checkpoint_seq,
            v_publication_id AS publication_id,
            '{{ target.schema }}' AS candidate_dataset,
            v_candidate_count AS candidate_row_count,
            v_candidate_sha256 AS candidate_sha256,
            v_new_pointer_version AS pointer_version;
    {% endset %}
    {% set result = run_query(sql) %}
    {% if result is not none and result.rows | length > 0 %}
        {% do log(
            'DATAFORGE_WEEK7_RESULT status=' ~ result.rows[0][0]
            ~ ' workflow_run_id=' ~ result.rows[0][1]
            ~ ' batch_id=' ~ result.rows[0][2]
            ~ ' publication_id=' ~ result.rows[0][6]
            ~ ' candidate_row_count=' ~ result.rows[0][8]
            ~ ' pointer_version=' ~ result.rows[0][10],
            info=True
        ) %}
    {% endif %}
{% endmacro %}
