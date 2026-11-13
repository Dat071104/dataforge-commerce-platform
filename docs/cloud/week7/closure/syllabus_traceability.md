# Week 7 syllabus traceability — P7.4.1

The user reported that the mentor approved GCP as the Azure/Fabric alternative. This is recorded as user-provided approval; no separate written approval artifact is claimed. GCP product mappings are nearest learning analogies, not exact equivalence.

| Syllabus checkpoint | Implementation and evidence | Status |
|---|---|---|
| Mini-project 1 API reused for Mini-project 3 | src/dataforge/weather.py and cloud/jobs/week7_weather/; actual Open-Meteo ERA5 request for 2026-11-05 and deployed API path recorded in api_to_gold_e2e_receipt.json | MET for the bounded slice |
| Immutable Bronze and provenance | weather_mini3/v1 raw, typed Parquet, invocation receipt, and manifest objects; exact GCS generations and hashes in api_to_gold_e2e_receipt.json | MET |
| Typed BigQuery landing and reconciliation | weather_mini3.weather_landing; Airflow post-load reconcile and exact manifest replay returned 3 rows and zero duplicate province/date grains | MET for the demonstrated date |
| dbt Silver, Gold, quality contracts, and publication | dbt/dataforge/models/weather/, tests, publication macro, and versioned weather Gold pointer; live build/test and exact source reconciliation | MET for the demonstrated date |
| Full-refresh and incremental parity | Isolated dbt_weather_mini3_full target compared bidirectionally against dbt_weather_mini3; three rows on each side and zero differences | MET for one bounded date |
| Real Airflow 3 integration and sensor | Separate cloud integration DAG; actual local Docker Airflow 3.4.0 DagRun called Cloud Run, sensed the immutable GCS receipt, reconciled landing, ran dbt, published, and checked Gold | MET for a successful live integration; hosted Airflow is not deployed |
| Airflow retry/failure handling | DAG has bounded retries, sensor reschedule, and timeouts; code contract tests pass | PARTIAL: no transient GCP task error was injected to observe an Airflow retry |
| Time-based cloud schedule | Cloud Scheduler automatically triggered Workflow execution 5028cbfb-e5a2-4596-b663-6d0d964a8c56; scheduler_execution_receipt.json | MET for one firing; schedule removed |
| External failure alert | One controlled Workflow failure opened a Monitoring incident and the user confirmed receipt of the single approved email; notification_delivery_receipt.md | MET for one delivery; channel/policy removed |
| dbt SCD2 history | Synthetic isolated source and dbt snapshot; three versions, valid windows, one current row, no overlaps, unchanged replay; dbt_scd2_history_receipt.json | MET for synthetic proof; authoritative Week 5 history untouched |
| Negative tests and recovery | Live unsettled-date rejection, wrong-generation rejection, exact replay, and pre-publication controlled failure; local contract tests cover malformed data, hash/schema corruption, and pointer guards | PARTIAL: live GCS tamper, bad BQ schema, bad dbt candidate, Airflow retry, and duplicate-trigger injection were not run |
| IAM and cost review | Scoped service identities, temporary IAM cleanup, no-change refreshed plan, query/Cloud Run usage, retained storage estimates; iam_cost_cleanup.md | MET with billing-account charges and free-tier use marked unknown |
| Public release | Independent controller returned `CLOUD_GO_WEEK7_SYLLABUS`; feature PR is permitted | PENDING: exact-head hosted CI and merge |

For the complete acceptance boundary, exact cloud IDs, and limitations, see acceptance_matrix.md and final_report.md. Historical Week 4/5/6/7 releases remain unchanged.
