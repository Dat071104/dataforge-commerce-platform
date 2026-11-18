{% test dq_week9_not_null(model, column_name) %}
    {{
        config(
            store_failures=(
                env_var('DATAFORGE_DQ_RESULTS_ENABLED', 'false') | lower == 'true'
            )
        )
    }}
    select {{ adapter.quote(column_name) }}
    from {{ model }}
    where {{ adapter.quote(column_name) }} is null
{% endtest %}

{% test dq_week9_unique(model, column_name) %}
    {{
        config(
            store_failures=(
                env_var('DATAFORGE_DQ_RESULTS_ENABLED', 'false') | lower == 'true'
            )
        )
    }}
    select {{ adapter.quote(column_name) }}
    from {{ model }}
    group by {{ adapter.quote(column_name) }}
    having count(*) > 1
{% endtest %}
