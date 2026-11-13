{% set weather_observation_date = var('weather_observation_date') %}

select
    cast(province_id as string) as province_id,
    cast(observation_date as date) as observation_date,
    cast(precipitation_mm as float64) as precipitation_mm,
    cast(temp_max_c as float64) as temp_max_c,
    cast(source as string) as source,
    cast(model as string) as model,
    cast(request_id as string) as request_id,
    cast(source_sha256 as string) as source_sha256,
    cast(manifest_uri as string) as manifest_uri,
    cast(manifest_generation as int64) as manifest_generation,
    cast(landed_at as timestamp) as landed_at
from {{ source('weather_mini3', 'weather_landing') }}
where observation_date = date('{{ weather_observation_date }}')
