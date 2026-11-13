{{ config(tags=['weather_mini3']) }}

select
    request_id,
    observation_date,
    count(*) as row_count,
    count(distinct province_id) as province_count
from {{ ref('stg_weather_mini3_landing') }}
group by request_id, observation_date
having count(*) != 3
    or count(distinct province_id) != 3
