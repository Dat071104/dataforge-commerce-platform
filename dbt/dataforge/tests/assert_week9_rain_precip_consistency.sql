{{
    config(
        tags=['weather_mini3', 'tier_blocking'],
        severity='error',
        error_if='>0',
        warn_if='>0',
        store_failures=(
            env_var('DATAFORGE_DQ_RESULTS_ENABLED', 'false') | lower == 'true'
        ),
        schema='dataforge_dq',
        meta={
            'check_id': 'G2.WEATHER.RAIN_PRECIP_CONSISTENCY',
            'layer': 'G2',
            'w9_severity': 'P1',
            'contract_version': '1.0.0'
        }
    )
}}

select *
from {{ ref('mart_weather_province_daily') }}
where
    rain_day is true
    and {{ dq_float_equal('precipitation_mm', '0.0') }}
