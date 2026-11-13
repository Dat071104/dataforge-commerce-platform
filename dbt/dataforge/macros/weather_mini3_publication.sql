{% macro _weather_mini3_validate_run_id(value) %}
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

{% macro publish_weather_mini3(workflow_run_id) %}
    {% do _weather_mini3_validate_run_id(workflow_run_id) %}
    {% if target.database != 'dataforge-p7-lab-d0f725' %}
        {{ exceptions.raise_compiler_error('publish_weather_mini3 is restricted to the approved DataForge project') }}
    {% endif %}
    {% if target.schema != 'dbt_weather_mini3' %}
        {{ exceptions.raise_compiler_error('publish_weather_mini3 is restricted to the dbt_weather_mini3 candidate dataset') }}
    {% endif %}

    {% set project = target.database %}
    {% set candidate = '`' ~ project ~ '.' ~ target.schema ~ '.fct_mini3_weather_daily`' %}
    {% set silver = '`' ~ project ~ '.' ~ target.schema ~ '.int_weather_daily`' %}
    {% set landing = '`' ~ project ~ '.weather_mini3.weather_landing`' %}
    {% set versions = '`' ~ project ~ '.gold_weather_mini3.weather_daily_versions`' %}
    {% set pointer = '`' ~ project ~ '.gold_weather_mini3.weather_publication_pointer`' %}
    {# The landing table requires an explicit partition predicate. The date bound
       covers all valid ERA5 history; every dbt query remains capped at 256 MiB. #}
    {% set landing_partition_filter = "observation_date >= DATE '1940-01-01'" %}

    {% set sql %}
        DECLARE p_workflow_run_id STRING DEFAULT '{{ workflow_run_id }}';
        DECLARE v_pointer_rows INT64 DEFAULT 0;
        DECLARE v_prior_version INT64 DEFAULT NULL;
        DECLARE v_candidate_count INT64 DEFAULT 0;
        DECLARE v_expected_count INT64 DEFAULT 0;
        DECLARE v_silver_count INT64 DEFAULT 0;
        DECLARE v_duplicate_count INT64 DEFAULT 0;
        DECLARE v_incomplete_date_count INT64 DEFAULT 0;
        DECLARE v_bad_count INT64 DEFAULT 0;
        DECLARE v_source_mismatch_count INT64 DEFAULT 0;
        DECLARE v_silver_mismatch_count INT64 DEFAULT 0;
        DECLARE v_candidate_sha256 STRING DEFAULT NULL;
        DECLARE v_existing_run_count INT64 DEFAULT 0;
        DECLARE v_existing_run_sha256 STRING DEFAULT NULL;
        DECLARE v_next_version INT64 DEFAULT NULL;
        DECLARE v_status STRING DEFAULT 'PUBLISHED';

        SET v_candidate_count = (SELECT COUNT(*) FROM {{ candidate }});
        SET v_expected_count = (
            SELECT COUNT(*)
            FROM (
                SELECT
                    province_id,
                    observation_date,
                    source,
                    model,
                    ROW_NUMBER() OVER (
                        PARTITION BY province_id, observation_date, source, model
                        ORDER BY manifest_generation DESC, landed_at DESC, request_id DESC
                    ) AS request_rank
                FROM {{ landing }}
                WHERE {{ landing_partition_filter }}
            )
            WHERE request_rank = 1
        );
        SET v_silver_count = (SELECT COUNT(*) FROM {{ silver }});
        SET v_duplicate_count = (
            SELECT COUNT(*)
            FROM (
                SELECT
                    request_id AS batch_key,
                    province_id,
                    observation_date,
                    CAST(NULL AS STRING) AS source,
                    CAST(NULL AS STRING) AS model
                FROM {{ landing }}
                WHERE {{ landing_partition_filter }}
                GROUP BY request_id, province_id, observation_date
                HAVING COUNT(*) > 1
                UNION ALL
                SELECT
                    CAST(NULL AS STRING) AS batch_key,
                    province_id,
                    observation_date,
                    source,
                    model
                FROM {{ candidate }}
                GROUP BY province_id, observation_date, source, model
                HAVING COUNT(*) > 1
            )
        );
        SET v_incomplete_date_count = (
            SELECT COUNT(*)
            FROM (
                SELECT request_id AS batch_key, observation_date
                FROM {{ landing }}
                WHERE {{ landing_partition_filter }}
                GROUP BY request_id, observation_date
                HAVING COUNT(*) != 3
                    OR COUNT(DISTINCT province_id) != 3
                    OR COUNT(DISTINCT manifest_uri) != 1
                    OR COUNT(DISTINCT manifest_generation) != 1
                UNION ALL
                SELECT CAST(NULL AS STRING) AS batch_key, observation_date
                FROM {{ candidate }}
                GROUP BY observation_date
                HAVING COUNT(*) != 3
                    OR COUNT(DISTINCT province_id) != 3
                    OR COUNT(DISTINCT request_id) != 1
                    OR COUNT(DISTINCT manifest_uri) != 1
                    OR COUNT(DISTINCT manifest_generation) != 1
            )
        );
        SET v_bad_count = (
            SELECT COUNT(*)
            FROM (
                SELECT
                    province_id, observation_date, precipitation_mm, temp_max_c,
                    source, model, request_id, source_sha256, manifest_uri,
                    manifest_generation, landed_at
                FROM {{ landing }}
                WHERE {{ landing_partition_filter }}
                UNION ALL
                SELECT
                    province_id, observation_date, precipitation_mm, temp_max_c,
                    source, model, request_id, source_sha256, manifest_uri,
                    manifest_generation, landed_at
                FROM {{ candidate }}
            ) AS checked_rows
            WHERE province_id IS NULL
               OR province_id NOT IN ('HCM', 'HN', 'DN')
               OR observation_date IS NULL
               OR source IS NULL
               OR source != 'open_meteo_era5'
               OR model IS NULL
               OR model != 'era5'
               OR request_id IS NULL
               OR NOT REGEXP_CONTAINS(request_id, r'^[0-9a-f]{64}$')
               OR source_sha256 IS NULL
               OR NOT REGEXP_CONTAINS(source_sha256, r'^[0-9a-f]{64}$')
               OR manifest_uri IS NULL
               OR NOT STARTS_WITH(
                   manifest_uri,
                   'gs://dataforge-p7-lab-d0f725-bronze/weather_mini3/v1/manifests/'
               )
               OR NOT ENDS_WITH(
                   manifest_uri,
                   CONCAT(
                       'observation_date=', CAST(observation_date AS STRING),
                       '/request_id=', request_id, '/manifest.json'
                   )
               )
               OR manifest_generation IS NULL
               OR manifest_generation <= 0
               OR landed_at IS NULL
               OR (precipitation_mm IS NOT NULL AND (
                   IS_NAN(precipitation_mm) OR IS_INF(precipitation_mm)
                   OR precipitation_mm < 0 OR precipitation_mm > 2000
               ))
               OR (temp_max_c IS NOT NULL AND (
                   IS_NAN(temp_max_c) OR IS_INF(temp_max_c)
                   OR temp_max_c < -90 OR temp_max_c > 70
               ))
        );
        SET v_source_mismatch_count = (
            SELECT COUNT(*)
            FROM (
                SELECT * EXCEPT(request_rank)
                FROM (
                    SELECT
                        *,
                        ROW_NUMBER() OVER (
                            PARTITION BY province_id, observation_date, source, model
                            ORDER BY manifest_generation DESC, landed_at DESC, request_id DESC
                        ) AS request_rank
                    FROM {{ landing }}
                    WHERE {{ landing_partition_filter }}
                )
                WHERE request_rank = 1
            ) AS expected
            FULL OUTER JOIN {{ candidate }} AS actual
              ON expected.province_id = actual.province_id
             AND expected.observation_date = actual.observation_date
             AND expected.source = actual.source
             AND expected.model = actual.model
            WHERE expected.province_id IS NULL
               OR actual.province_id IS NULL
               OR expected.precipitation_mm IS DISTINCT FROM actual.precipitation_mm
               OR expected.temp_max_c IS DISTINCT FROM actual.temp_max_c
               OR expected.request_id IS DISTINCT FROM actual.request_id
               OR expected.source_sha256 IS DISTINCT FROM actual.source_sha256
               OR expected.manifest_uri IS DISTINCT FROM actual.manifest_uri
               OR expected.manifest_generation IS DISTINCT FROM actual.manifest_generation
               OR expected.landed_at IS DISTINCT FROM actual.landed_at
        );
        SET v_silver_mismatch_count = (
            SELECT COUNT(*)
            FROM {{ silver }} AS expected
            FULL OUTER JOIN {{ candidate }} AS actual
              ON expected.province_id = actual.province_id
             AND expected.observation_date = actual.observation_date
             AND expected.source = actual.source
             AND expected.model = actual.model
            WHERE expected.province_id IS NULL
               OR actual.province_id IS NULL
               OR expected.precipitation_mm IS DISTINCT FROM actual.precipitation_mm
               OR expected.temp_max_c IS DISTINCT FROM actual.temp_max_c
               OR expected.request_id IS DISTINCT FROM actual.request_id
               OR expected.source_sha256 IS DISTINCT FROM actual.source_sha256
               OR expected.manifest_uri IS DISTINCT FROM actual.manifest_uri
               OR expected.manifest_generation IS DISTINCT FROM actual.manifest_generation
               OR expected.landed_at IS DISTINCT FROM actual.landed_at
        );
        ASSERT v_candidate_count > 0 AS 'Weather publication refuses an empty Gold candidate';
        ASSERT v_candidate_count = v_expected_count
          AS 'Weather Gold row count differs from the raw landing latest-version count';
        ASSERT v_candidate_count = v_silver_count
          AS 'Weather Gold row count differs from the conformed Silver count';
        ASSERT v_candidate_count = 3 * (
            SELECT COUNT(DISTINCT observation_date) FROM {{ candidate }}
        ) AS 'Weather Gold row count differs from the fixed three-province date coverage';
        ASSERT v_duplicate_count = 0 AS 'Weather Gold key is not unique at province/date/source/model grain';
        ASSERT v_incomplete_date_count = 0
          AS 'Every weather date must contain exactly one row for each allowlisted province';
        ASSERT v_bad_count = 0 AS 'Weather Gold contains an invalid source, key, provenance value, or metric';
        ASSERT v_source_mismatch_count = 0
          AS 'Weather Gold does not reconcile row-for-row to raw landing latest versions';
        ASSERT v_silver_mismatch_count = 0
          AS 'Weather Gold does not reconcile row-for-row to conformed Silver';

        SET v_candidate_sha256 = (
            SELECT TO_HEX(SHA256(COALESCE(STRING_AGG(
                TO_JSON_STRING(STRUCT(
                    province_id,
                    observation_date,
                    precipitation_mm,
                    temp_max_c,
                    precipitation_condition,
                    source,
                    model,
                    request_id,
                    source_sha256,
                    manifest_uri,
                    manifest_generation,
                    landed_at
                )),
                '\n' ORDER BY province_id, observation_date, source, model
            ), '')))
            FROM {{ candidate }}
        );

        SET v_existing_run_count = (
            SELECT COUNT(*) FROM {{ versions }} WHERE publication_run_id = p_workflow_run_id
        );
        IF v_existing_run_count > 0 THEN
            SET v_existing_run_sha256 = (
                SELECT ANY_VALUE(published_sha256)
                FROM {{ versions }}
                WHERE publication_run_id = p_workflow_run_id
            );
            ASSERT v_existing_run_count = v_candidate_count
              AS 'Existing weather publication run has an unexpected row count';
            ASSERT v_existing_run_sha256 = v_candidate_sha256
              AS 'A workflow_run_id cannot be replayed with changed weather content';
            SET v_status = 'NO_OP';
        ELSE
            SET v_pointer_rows = (SELECT COUNT(*) FROM {{ pointer }});
            ASSERT v_pointer_rows <= 1
              AS 'Weather publication pointer contains more than one row';
            IF v_pointer_rows = 0 THEN
                MERGE {{ pointer }} AS current_pointer
                USING (SELECT 1 AS singleton_id) AS seed
                  ON current_pointer.singleton_id = seed.singleton_id
                WHEN NOT MATCHED THEN
                  INSERT (
                      singleton_id,
                      publication_version,
                      publication_run_id,
                      published_sha256,
                      published_row_count,
                      publication_is_current,
                      updated_at
                  )
                  VALUES (
                      seed.singleton_id,
                      0,
                      NULL,
                      NULL,
                      0,
                      FALSE,
                      CURRENT_TIMESTAMP()
                  );
            END IF;
            SET v_pointer_rows = (SELECT COUNT(*) FROM {{ pointer }});
            ASSERT v_pointer_rows = 1
              AND (SELECT COUNTIF(singleton_id = 1) FROM {{ pointer }}) = 1
              AS 'Weather publication pointer must contain exactly the singleton row';

            BEGIN TRANSACTION;
            SET v_prior_version = (
                SELECT publication_version FROM {{ pointer }} WHERE singleton_id = 1
            );
            ASSERT v_prior_version IS NOT NULL AND v_prior_version >= 0
              AS 'Weather publication pointer version is invalid';
            SET v_next_version = v_prior_version + 1;

            INSERT INTO {{ versions }} (
                publication_version,
                publication_run_id,
                published_sha256,
                published_row_count,
                published_at,
                candidate_dataset,
                province_id,
                observation_date,
                precipitation_mm,
                temp_max_c,
                precipitation_condition,
                source,
                model,
                request_id,
                source_sha256,
                manifest_uri,
                manifest_generation,
                landed_at
            )
            SELECT
                v_next_version,
                p_workflow_run_id,
                v_candidate_sha256,
                v_candidate_count,
                CURRENT_TIMESTAMP(),
                '{{ target.schema }}',
                province_id,
                observation_date,
                precipitation_mm,
                temp_max_c,
                precipitation_condition,
                source,
                model,
                request_id,
                source_sha256,
                manifest_uri,
                manifest_generation,
                landed_at
            FROM {{ candidate }};

            UPDATE {{ pointer }}
            SET publication_version = v_next_version,
                publication_run_id = p_workflow_run_id,
                published_sha256 = v_candidate_sha256,
                published_row_count = v_candidate_count,
                publication_is_current = TRUE,
                updated_at = CURRENT_TIMESTAMP()
            WHERE singleton_id = 1
              AND publication_version = v_prior_version;
            ASSERT @@row_count = 1
              AS 'Weather publication pointer compare-and-set failed';
            COMMIT TRANSACTION;
        END IF;

        SELECT
            v_status AS status,
            p_workflow_run_id AS workflow_run_id,
            v_candidate_count AS candidate_row_count,
            v_candidate_sha256 AS candidate_sha256,
            (SELECT publication_version FROM {{ pointer }} WHERE singleton_id = 1) AS pointer_version;
    {% endset %}

    {% if execute %}
        {% set result = run_query(sql) %}
        {% if result is not none and result.rows | length > 0 %}
            {% do log(
                'DATAFORGE_WEATHER_MINI3_PUBLISH status=' ~ result.rows[0][0]
                ~ ' workflow_run_id=' ~ result.rows[0][1]
                ~ ' rows=' ~ result.rows[0][2]
                ~ ' sha256=' ~ result.rows[0][3]
                ~ ' pointer_version=' ~ result.rows[0][4],
                info=True
            ) %}
        {% endif %}
    {% else %}
        {% do log('publish_weather_mini3 is an execute-only operation; no warehouse statement ran.', info=True) %}
    {% endif %}
{% endmacro %}
