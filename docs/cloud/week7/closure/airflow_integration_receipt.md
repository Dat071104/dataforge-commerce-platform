# Mini-project 3 Airflow integration

## Result

**Live integration:** PASS. A one-shot local Airflow 3.4.0 DagRun executed the real GCP data plane and published three weather rows. Airflow itself, including the DAG runner, was local Docker; no Composer, GKE, or persistent Airflow service was deployed.

The successful DagRun was:

- DAG: dataforge_week7_weather_cloud
- Airflow run: manual__2026-11-12T09:17:10.037023+00:00
- Airflow invocation receipt: 44dcf9562a79445bf7bf460a0508164beecca0bc1833b3bcaef62f668b45ac82
- Observation date: 2026-11-05; timezone: Asia/Ho_Chi_Minh; settling delay: seven days.
- Request: f0c61c7a30afdd501bf77f3a669d2a842a6bea08d1dd791374dfaa6dc04a4139
- Exact manifest generation: 1794475149037958.
- Final state: SUCCESS; 3 landing rows reconciled; 3 Gold rows across HCM, HN, DN; zero invalid metrics.
- Gold publication: version 4; hash acdadfc3d1cd8a8d391aea010acf547a73ef47b1e9fa8608c0c01a00d7e2afde.

Cloud Run execution names are recorded in api_to_gold_e2e_receipt.json. The successful run used the dedicated Airflow identity and read-only mounted keyless ADC file. The run did not use a static service-account key. The Scheduler preflight returned ABSENT, so no cloud trigger was active concurrently.

## DAG stages

The integration DAG is in labs/airflow_reference/dags/dataforge_week7_weather_cloud.py. It is created paused and requires an explicit cloud_integration configuration. It declares a 09:00 Asia/Ho_Chi_Minh schedule, catchup=False, max_active_runs=1, bounded retries, task execution timeouts, and a two-hour DagRun timeout. The actual demonstration used the one-shot airflow dags test command; a persistent scheduler was not started.

    resolve_cloud_request ─┬─ verify_gcp_schedule_paused ─┐
                          └─ execute_api_ingest ─────────┴─ wait_for_gcs_invocation_receipt
                               → read_execution_receipt
                               → load_bigquery_landing
                               → verify_landing_reconciliation
                               → dbt_weather_build
                               → dbt_weather_test
                               → publish_weather_gold
                               → verify_published_gold
                               → record_airflow_execution_receipt

The reschedule sensor waited for a real immutable GCS invocation receipt. Its downstream task verified the schema, invocation ID, date, province allowlist, attribution, row count, request digest, manifest URI, and generation. The landing task read that exact manifest generation, checked the raw and typed objects, and merged into the isolated BigQuery landing table. A separate read-only reconciliation ran after the merge.

The DAG then invoked the separate weather dbt Cloud Run Job for build, test, guarded publication, and Gold verification. XCom contained only compact identifiers, object URI/generation, Cloud Run execution names, a query job ID, and aggregate counts. It did not carry provider rows, tokens, or credentials.

## Recovery evidence

An early integration attempt exposed an ordering defect: reconciliation ran before landing. That attempt failed before publication. The DAG was changed to load first and then verify, and the successful DagRun above confirmed the corrected order. A separate runner invocation initially failed because the Docker image entrypoint was not overridden; the runner was fixed and the next DagRun completed. These attempts did not change accepted commerce tables.

The live successful DagRun completed without consuming an Airflow retry. Bounded retry configuration is verified by the DAG contract tests, but a transient cloud task failure followed by an Airflow retry was not injected. That specific retry scenario remains PARTIAL.

## Keyless boundary and tests

The optional runner mounts only one explicitly selected keyless ADC file, read-only, at /run/dataforge/credentials/application_default_credentials.json. It impersonates the dedicated dataforge-week7-airflow service account. The user's temporary Token Creator binding was removed after the demonstration. The runner rejects static service-account key JSON and validates the target project, region, bucket, jobs, and principal.

The normal fixture DAG and its network=none CI path are unchanged. The integration runner was locally built from a pinned Airflow 3.4.0 base and was not pushed to Artifact Registry.

Airflow 3 authoring and sensor behavior follow the Airflow 3.4 public interface, sensor reschedule, and task timeout documentation:

- https://airflow.apache.org/docs/apache-airflow/3.4.0/public-airflow-interface.html
- https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/sensors.html
- https://airflow.apache.org/docs/apache-airflow/3.4.0/core-concepts/tasks.html

## Notification boundary

The Airflow failure callback writes a redacted local log record only. The actual external failure notification was delivered by the separate Cloud Workflows plus Cloud Monitoring test documented in notification_delivery_receipt.md. Airflow callback logs are not counted as external notification evidence.
