{{ config(tags=['weather_mini3']) }}

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
