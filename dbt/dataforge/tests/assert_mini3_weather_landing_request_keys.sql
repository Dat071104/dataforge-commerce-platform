{{ config(tags=['weather_mini3']) }}

select
    request_id,
    province_id,
    observation_date
from {{ ref('stg_weather_mini3_landing') }}
group by request_id, province_id, observation_date
having count(*) > 1
