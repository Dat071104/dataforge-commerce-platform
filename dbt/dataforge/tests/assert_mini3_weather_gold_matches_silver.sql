{{ config(tags=['weather_mini3']) }}

with silver as (
    select * from {{ ref('int_weather_daily') }}
), gold as (
    select * from {{ ref('fct_mini3_weather_daily') }}
), compared as (
    select
        silver.province_id as silver_province_id,
        gold.province_id as gold_province_id,
        silver.observation_date as silver_observation_date,
        gold.observation_date as gold_observation_date,
        silver.source as silver_source,
        gold.source as gold_source,
        silver.model as silver_model,
        gold.model as gold_model,
        silver.precipitation_mm as silver_precipitation_mm,
        gold.precipitation_mm as gold_precipitation_mm,
        silver.temp_max_c as silver_temp_max_c,
        gold.temp_max_c as gold_temp_max_c,
        silver.request_id as silver_request_id,
        gold.request_id as gold_request_id,
        silver.manifest_generation as silver_manifest_generation,
        gold.manifest_generation as gold_manifest_generation
    from silver
    full outer join gold
      on silver.province_id = gold.province_id
     and silver.observation_date = gold.observation_date
     and silver.source = gold.source
     and silver.model = gold.model
)
select *
from compared
where silver_province_id is null
   or gold_province_id is null
   or silver_precipitation_mm is distinct from gold_precipitation_mm
   or silver_temp_max_c is distinct from gold_temp_max_c
   or silver_request_id is distinct from gold_request_id
   or silver_manifest_generation is distinct from gold_manifest_generation
