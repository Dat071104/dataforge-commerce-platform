{{ config(tags=['weather_mini3']) }}

select
    province_id,
    observation_date,
    count(*) as row_count
from {{ ref('mart_weather_province_daily') }}
group by province_id, observation_date
having count(*) > 1
