# S10 Airflow UI capture

- Method: S10-M fallback using the already authenticated Chrome session; page views only.
- Browser: Airflow 3 UI through the existing IAP tunnel at 127.0.0.1:18080.
- No password was read or entered during these captures. The password value is absent from the images and this manifest.
- The separate S10-M2 headless attempt returned LoginError; it was not retried.
- No trigger, clear, pause, edit, admin, user, or connection page was used.
- Visual check: no email address or password is visible in the final images.
- An initial blank Graph attempt was not used; the final evidence Graph image is rendered.

## s10-grid-20261118.png

- URL: http://127.0.0.1:18080/dags/dataforge_week7_weather_cloud/runs/scheduled__2026-11-18T02:00:00+00:00
- Captured at: 2026-11-18T13:08:20+07:00
- Verified text markers: DAG dataforge_week7_weather_cloud; scheduled__2026-11-18T02:00:00+00:00; run status Success; Grid view selected; visible run columns; DOM listed S6, S3 canary, and Nov 6 backfill
- Pixel size: 1600x1200

## s10-graph-20261118.png

- URL: http://127.0.0.1:18080/dags/dataforge_week7_weather_cloud/runs/scheduled__2026-11-18T02:00:00+00:00
- Captured at: 2026-11-18T13:15:19+07:00
- Verified text markers: DAG dataforge_week7_weather_cloud; scheduled__2026-11-18T02:00:00+00:00; Graph view selected; 16 task IDs visible; run status Success; all task nodes green
- Pixel size: 1600x1200

## s10-task-log-20261118.png

- URL: http://127.0.0.1:18080/dags/dataforge_week7_weather_cloud/runs/scheduled__2026-11-18T02:00:00+00:00/tasks/verify_published_gold
- Captured at: 2026-11-18T13:12:56+07:00
- Verified text markers: DAG dataforge_week7_weather_cloud; scheduled__2026-11-18T02:00:00+00:00; verify_published_gold; task Success; try 1 verified from task-instance table; row_count 3; province_count 3; invalid_metric_rows 0
- Pixel size: 1600x1200

## s10-s6-retry-20261118.png

- URL: http://127.0.0.1:18080/dags/dataforge_week7_weather_cloud/runs/manual__s6_transient_once_20261101_20261118T111125/tasks/execute_api_ingest?try_number=1
- Captured at: 2026-11-18T13:13:47+07:00
- Verified text markers: DAG dataforge_week7_weather_cloud; manual__s6_transient_once_20261101_20261118T111125; execute_api_ingest; Task Tries selector shows try 1 failed and try 2 success; transient_once; cloud_run_submitted false; failed before Cloud Run submission
- Pixel size: 1600x1200

## s10-s6-retry-try2-20261118.png

- URL: http://127.0.0.1:18080/dags/dataforge_week7_weather_cloud/runs/manual__s6_transient_once_20261101_20261118T111125/tasks/execute_api_ingest?try_number=2
- Captured at: 2026-11-18T13:14:46+07:00
- Verified text markers: DAG dataforge_week7_weather_cloud; manual__s6_transient_once_20261101_20261118T111125; execute_api_ingest; Task Tries selector shows try 2 success; Cloud Run submitted; same invocation ID 1c533386ec3b478d558cf64115dfeb1d7af4726e6507beeb11d7461f326f040c verified in s6-execution-readback-20261118.log and s6-airflow-receipt-20261118.log
- Pixel size: 1600x1200
