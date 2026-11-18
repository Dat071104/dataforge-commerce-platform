{{
    config(
        tags=['weather_mini3', 'tier_blocking'],
        severity='error',
        error_if='>0',
        warn_if='>0',
        store_failures=(env_var('DATAFORGE_DQ_RESULTS_ENABLED', 'false') | lower == 'true'),
        schema='dataforge_dq',
        meta={
            'check_id': 'G2.WEATHER.GRAIN_UNIQUE',
            'layer': 'G2',
            'w9_severity': 'P1',
            'contract_version': '1.0.0'
        }
    )
}}

with observations as (
    select
        'silver' as model_name,
        province_id,
        observation_date,
        source,
        model
    from {{ ref('int_weather_daily') }}
    union all
    select
        'gold' as model_name,
        province_id,
        observation_date,
        source,
        model
    from {{ ref('fct_mini3_weather_daily') }}
)
select
    model_name,
    province_id,
    observation_date,
    source,
    model
from observations
group by model_name, province_id, observation_date, source, model
having count(*) > 1
