{{ config(tags=['weather_mini3']) }}

select
    province_id,
    observation_date,
    precipitation_mm,
    temp_max_c,
    rain_day,
    precipitation_7d_mm,
    temp_max_30d_mean_c,
    temp_max_30d_anomaly_c
from {{ ref('mart_weather_province_daily') }}
where (precipitation_mm is not null and (precipitation_mm < 0 or precipitation_mm > 2000))
   or (temp_max_c is not null and (temp_max_c < -90 or temp_max_c > 70))
   or (rain_day is distinct from (
            case
                when precipitation_mm is null then cast(null as bool)
                else precipitation_mm > 0
            end
       ))
   or (precipitation_observed_days_7d < 0 or precipitation_observed_days_7d > 7)
   or (precipitation_7d_mm is not null and (precipitation_7d_mm < 0 or precipitation_7d_mm > 14000))
   or (temp_max_observed_days_30d < 0 or temp_max_observed_days_30d > 30)
   or (temp_max_30d_mean_c is not null and (temp_max_30d_mean_c < -90 or temp_max_30d_mean_c > 70))
   or (temp_max_30d_anomaly_c is not null and (temp_max_30d_anomaly_c < -160 or temp_max_30d_anomaly_c > 160))
   or (precipitation_observed_days_7d < 7 and precipitation_7d_mm is not null)
   or (temp_max_observed_days_30d < 30 and (temp_max_30d_mean_c is not null or temp_max_30d_anomaly_c is not null))
