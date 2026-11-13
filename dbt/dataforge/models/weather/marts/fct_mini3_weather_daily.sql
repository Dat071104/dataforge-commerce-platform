select
    province_id,
    observation_date,
    precipitation_mm,
    temp_max_c,
    case
        when precipitation_mm is null then 'unknown'
        when precipitation_mm = 0 then 'dry'
        else 'wet'
    end as precipitation_condition,
    source,
    model,
    request_id,
    source_sha256,
    manifest_uri,
    manifest_generation,
    landed_at
from {{ ref('int_weather_daily') }}
