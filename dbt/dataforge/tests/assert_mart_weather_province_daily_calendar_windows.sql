{{ config(tags=['weather_mini3']) }}

with weather as (
    select province_id, observation_date, precipitation_mm, temp_max_c
    from {{ ref('fct_mini3_weather_daily') }}
    where source = 'open_meteo_era5'
      and model = 'era5'
), expected_7d as (
    select
        current_weather.province_id,
        current_weather.observation_date,
        countif(prior_weather.precipitation_mm is not null) as precipitation_observed_days_7d,
        case
            when countif(prior_weather.precipitation_mm is not null) = 7
                then sum(prior_weather.precipitation_mm)
        end as precipitation_7d_mm
    from weather as current_weather
    left join weather as prior_weather
        on prior_weather.province_id = current_weather.province_id
       and prior_weather.observation_date between date_sub(current_weather.observation_date, interval 6 day)
                                              and current_weather.observation_date
    group by current_weather.province_id, current_weather.observation_date
), expected_30d as (
    select
        current_weather.province_id,
        current_weather.observation_date,
        countif(prior_weather.temp_max_c is not null) as temp_max_observed_days_30d,
        case
            when countif(prior_weather.temp_max_c is not null) = 30
                then avg(prior_weather.temp_max_c)
        end as temp_max_30d_mean_c
    from weather as current_weather
    left join weather as prior_weather
        on prior_weather.province_id = current_weather.province_id
       and prior_weather.observation_date between date_sub(current_weather.observation_date, interval 29 day)
                                              and current_weather.observation_date
    group by current_weather.province_id, current_weather.observation_date
), expected as (
    select
        expected_7d.province_id,
        expected_7d.observation_date,
        expected_7d.precipitation_observed_days_7d,
        expected_7d.precipitation_7d_mm,
        expected_30d.temp_max_observed_days_30d,
        expected_30d.temp_max_30d_mean_c
    from expected_7d
    join expected_30d using (province_id, observation_date)
), comparison as (
    select
        actual.province_id,
        actual.observation_date,
        actual.precipitation_observed_days_7d,
        expected.precipitation_observed_days_7d as expected_precipitation_observed_days_7d,
        actual.precipitation_7d_mm,
        expected.precipitation_7d_mm as expected_precipitation_7d_mm,
        actual.temp_max_observed_days_30d,
        expected.temp_max_observed_days_30d as expected_temp_max_observed_days_30d,
        actual.temp_max_30d_mean_c,
        expected.temp_max_30d_mean_c as expected_temp_max_30d_mean_c,
        actual.temp_max_30d_anomaly_c,
        case
            when expected.temp_max_observed_days_30d = 30
                then actual.temp_max_c - expected.temp_max_30d_mean_c
        end as expected_temp_max_30d_anomaly_c
    from {{ ref('mart_weather_province_daily') }} as actual
    join expected using (province_id, observation_date)
)
select *
from comparison
where precipitation_observed_days_7d != expected_precipitation_observed_days_7d
   or precipitation_7d_mm is distinct from expected_precipitation_7d_mm
   or temp_max_observed_days_30d != expected_temp_max_observed_days_30d
   or temp_max_30d_mean_c is distinct from expected_temp_max_30d_mean_c
   or temp_max_30d_anomaly_c is distinct from expected_temp_max_30d_anomaly_c
