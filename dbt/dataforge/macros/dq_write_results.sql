{% macro dq_write_run_results(results) %}
    {% if env_var('DATAFORGE_DQ_RESULTS_ENABLED', 'false') | lower != 'true' %}
        {{ return('') }}
    {% endif %}
    {% if target.type != 'bigquery' or not execute %}
        {{ return('') }}
    {% endif %}

    {% set rows = [] %}
    {% set run_id = invocation_id | replace("'", "''") %}
    {% for result in results %}
        {% set check_id = none %}
        {% set layer = 'G2' %}
        {% set severity = none %}
        {% set contract_version = '1.0.0' %}
        {% set threshold = 'zero failing rows' %}

        {% if result.node is defined and result.node.resource_type == 'test' %}
            {% set metadata = result.node.config.meta | default({}, true) %}
            {% set check_id = metadata.get('check_id') %}
            {% set layer = metadata.get('layer', 'G2') %}
            {% set severity = metadata.get('w9_severity') %}
            {% set contract_version = metadata.get('contract_version', '1.0.0') %}
        {% elif result.node is defined and result.node.resource_type == 'source' %}
            {% if result.node.source_name == 'weather_mini3'
                and result.node.name == 'weather_landing' %}
                {% set check_id = 'G2.SOURCE.FRESHNESS' %}
                {% set layer = 'G2' %}
                {% if result.status == 'error' %}
                    {% set severity = 'P1' %}
                {% elif result.status == 'warn' %}
                    {% set severity = 'P2' %}
                {% else %}
                    {% set severity = 'P2' %}
                {% endif %}
                {% set threshold = 'warn_after=36h,error_after=72h' %}
            {% endif %}
        {% endif %}

        {% if check_id and severity %}
            {% set safe_check_id = check_id | string | replace("'", "''") %}
            {% set safe_layer = layer | string | replace("'", "''") %}
            {% set safe_severity = severity | string | replace("'", "''") %}
            {% set safe_threshold = threshold | string | replace("'", "''") %}
            {% set status = result.status | string | lower %}
            {% if status in ['pass', 'success'] %}
                {% set dq_status = 'PASS' %}
            {% elif status in ['warn'] %}
                {% set dq_status = 'WARN' %}
            {% else %}
                {% set dq_status = 'FAIL' %}
            {% endif %}
            {% set failures = result.failures | default(0, true) | int %}
            {% set result_dataset = target.schema %}
            {% if result.node.resource_type == 'source' %}
                {% set result_dataset = result.node.schema | default(target.schema, true) %}
            {% endif %}
            {% set result_date = var('weather_observation_date', '') | string %}
            {% if not result_date or result_date == '1970-01-01' %}
                {% set result_date = run_started_at.strftime('%Y-%m-%d') %}
            {% endif %}
            {% set safe_observed_status = status | replace("'", "''") %}
            {% set safe_dataset = result_dataset | string | replace("'", "''") %}
            {% set safe_result_date = result_date | replace("'", "''") %}
            {% set observed_sql =
                "TO_JSON_STRING(STRUCT('" ~ safe_observed_status ~ "' AS status, "
                ~ failures ~ " AS failures, '" ~ safe_dataset ~ "' AS dataset, '"
                ~ safe_result_date ~ "' AS date))"
            %}
            {% do rows.append(
                "STRUCT('" ~ run_id ~ "' AS run_id, '" ~ safe_check_id ~ "' AS check_id, '"
                ~ safe_layer ~ "' AS layer, '" ~ safe_severity ~ "' AS severity, '"
                ~ dq_status ~ "' AS status, " ~ observed_sql ~ " AS observed, '"
                ~ safe_threshold ~ "' AS threshold, " ~ failures ~ " AS failing_rows, '"
                ~ contract_version ~ "' AS contract_version, CURRENT_TIMESTAMP() AS ts)"
            ) %}
        {% endif %}
    {% endfor %}

    {% if rows %}
        {% set table_name = '`' ~ target.database ~ '.dataforge_dq.dq_results`' %}
        {% set create_sql %}
            CREATE TABLE IF NOT EXISTS {{ table_name }} (
                run_id STRING NOT NULL,
                check_id STRING NOT NULL,
                layer STRING NOT NULL,
                severity STRING NOT NULL,
                status STRING NOT NULL,
                observed STRING,
                threshold STRING,
                failing_rows INT64 NOT NULL,
                contract_version STRING NOT NULL,
                ts TIMESTAMP NOT NULL
            )
            PARTITION BY DATE(ts)
            CLUSTER BY check_id, layer, severity
        {% endset %}
        {% do run_query(create_sql) %}
        {% set sql %}
            INSERT INTO {{ table_name }}
                (run_id, check_id, layer, severity, status, observed, threshold,
                 failing_rows, contract_version, ts)
            SELECT run_id, check_id, layer, severity, status, observed, threshold,
                   failing_rows, contract_version, ts
            FROM UNNEST([{{ rows | join(',') }}])
        {% endset %}
        {% do run_query(sql) %}
    {% endif %}
{% endmacro %}
