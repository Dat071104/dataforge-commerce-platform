{{ config(tags=['weather_mini3']) }}

-- The dashboard grain is one observation per province/local date. This mart
-- intentionally uses the single approved ERA5 source/model so provider rows
-- cannot multiply that grain if another source is added later.
with weather as (
    select
        province_id,
        observation_date,
        precipitation_mm,
        temp_max_c
    from {{ ref('fct_mini3_weather_daily') }}
    where source = 'open_meteo_era5'
      and model = 'era5'
), calendar_windows as (
    select
        province_id,
        observation_date,
        precipitation_mm,
        temp_max_c,
        count(precipitation_mm) over (
            partition by province_id
            order by unix_date(observation_date)
            range between 6 preceding and current row
        ) as precipitation_observed_days_7d,
        sum(precipitation_mm) over (
            partition by province_id
            order by unix_date(observation_date)
            range between 6 preceding and current row
        ) as observed_precipitation_7d_mm,
        count(temp_max_c) over (
            partition by province_id
            order by unix_date(observation_date)
            range between 29 preceding and current row
        ) as temp_max_observed_days_30d,
        avg(temp_max_c) over (
            partition by province_id
            order by unix_date(observation_date)
            range between 29 preceding and current row
        ) as observed_temp_max_30d_mean_c
    from weather
)
select
    province_id,
    observation_date,
    precipitation_mm,
    temp_max_c,
    case
        when precipitation_mm is null then cast(null as bool)
        else precipitation_mm > 0
    end as rain_day,
    precipitation_observed_days_7d,
    case
        when precipitation_observed_days_7d = 7 then observed_precipitation_7d_mm
        else cast(null as float64)
    end as precipitation_7d_mm,
    temp_max_observed_days_30d,
    case
        when temp_max_observed_days_30d = 30 then observed_temp_max_30d_mean_c
        else cast(null as float64)
    end as temp_max_30d_mean_c,
    case
        when temp_max_observed_days_30d = 30 and temp_max_c is not null
            then temp_max_c - observed_temp_max_30d_mean_c
        else cast(null as float64)
    end as temp_max_30d_anomaly_c
from calendar_windows
