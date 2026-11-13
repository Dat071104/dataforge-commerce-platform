{{ config(tags=['weather_mini3']) }}

select
    province_id,
    observation_date,
    precipitation_mm,
    temp_max_c,
    source_sha256,
    manifest_generation
from {{ ref('stg_weather_mini3_landing') }}
where (precipitation_mm is not null and (precipitation_mm < 0 or precipitation_mm > 2000))
   or (temp_max_c is not null and (temp_max_c < -90 or temp_max_c > 70))
   or not regexp_contains(source_sha256, r'^[0-9a-f]{64}$')
   or manifest_generation <= 0
