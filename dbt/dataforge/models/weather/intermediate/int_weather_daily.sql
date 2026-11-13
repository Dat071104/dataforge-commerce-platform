{{
    config(
        incremental_strategy='merge',
        unique_key=['province_id', 'observation_date', 'source', 'model'],
        on_schema_change='fail'
    )
}}

with landing as (
    select *
    from {{ ref('stg_weather_mini3_landing') }}
    {% if is_incremental() %}
    where landed_at >= (
        select coalesce(
            timestamp_sub(max(landed_at), interval 5 minute),
            timestamp('1970-01-01 00:00:00+00')
        )
        from {{ this }}
    )
    {% endif %}
), ranked as (
    select
        *,
        row_number() over (
            partition by province_id, observation_date, source, model
            order by manifest_generation desc, landed_at desc, request_id desc
        ) as request_rank
    from landing
)
select
    province_id,
    observation_date,
    precipitation_mm,
    temp_max_c,
    source,
    model,
    request_id,
    source_sha256,
    manifest_uri,
    manifest_generation,
    landed_at
from ranked
where request_rank = 1
