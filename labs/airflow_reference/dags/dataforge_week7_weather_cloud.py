"""Opt-in Airflow 3 integration DAG for the Mini-project 3 weather slice.

The DAG is paused on creation and performs no cloud access unless a DagRun is
explicitly started with ``{"mode": "cloud_integration"}``. The local fixture
DAG remains isolated and unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import timedelta
from typing import Any

import pendulum
from airflow.sdk import BaseSensorOperator, dag, get_current_context, task
from airflow.sdk.exceptions import AirflowException, AirflowFailException
from dataforge_week7_weather_logic import (
    BRONZE_BUCKET,
    PROJECT_ID,
    PROVINCES,
    REGION,
    ContractError,
    invocation_receipt_object,
    resolve_request,
    validate_execution_receipt,
    weather_dbt_vars_argument,
)

DAG_ID = "dataforge_week7_weather_cloud"
TIMEZONE = "Asia/Ho_Chi_Minh"
INGEST_JOB = "dataforge-week7-weather-ingest"
DBT_JOB = "dataforge-week7-weather-dbt"
SCHEDULER_JOB = "dataforge-week7-weather-daily"
GOOGLE_APPLICATION_CREDENTIALS_PATH = (
    "/run/dataforge/credentials/application_default_credentials.json"
)
_LOGGER = logging.getLogger("airflow.task")
_CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_CLOUD_RUN_TASK_TIMEOUT = timedelta(minutes=40)
_CLOUD_RUN_POLL_SECONDS = 10
_CLOUD_RUN_POLL_TIMEOUT_SECONDS = 35 * 60
_ALLOWED_JOB_NAMES = {INGEST_JOB, DBT_JOB}
_AIRFLOW_CALLER = re.compile(
    rf"^dataforge-week7-airflow@{re.escape(PROJECT_ID)}\.iam\.gserviceaccount\.com$"
)


def local_failure_log(context: dict[str, Any]) -> None:
    """Log redacted Airflow failure metadata; this is not external delivery."""
    task_instance = context.get("task_instance")
    dag_run = context.get("dag_run")
    exception = context.get("exception")
    receipt = {
        "hook": "LOCAL_AIRFLOW_LOG_ONLY",
        "dag_id": getattr(dag_run, "dag_id", None),
        "run_id": getattr(dag_run, "run_id", None),
        "task_id": getattr(task_instance, "task_id", None),
        "try_number": getattr(task_instance, "try_number", None),
        "exception_type": type(exception).__name__ if exception is not None else None,
        "external_notification_sent": False,
    }
    _LOGGER.error("DATAFORGE_AIRFLOW_WEATHER_FAILURE %s", json.dumps(receipt, sort_keys=True))


def _impersonated_credentials():
    """Load one explicitly mounted keyless ADC source and impersonate the scoped caller."""
    configured_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if configured_path != GOOGLE_APPLICATION_CREDENTIALS_PATH:
        raise AirflowFailException(
            "cloud mode requires the explicit read-only keyless ADC mount"
        )
    if not os.path.isfile(GOOGLE_APPLICATION_CREDENTIALS_PATH):
        raise AirflowFailException("the explicit keyless ADC file is unavailable")

    target_principal = os.environ.get("DATAFORGE_AIRFLOW_IMPERSONATION_SERVICE_ACCOUNT", "")
    if not _AIRFLOW_CALLER.fullmatch(target_principal):
        raise AirflowFailException("the configured Airflow caller identity is not approved")

    try:
        import google.auth
        from google.auth import impersonated_credentials
        from google.oauth2 import service_account

        source_credentials, _ = google.auth.default(scopes=[_CLOUD_SCOPE])
        if isinstance(source_credentials, service_account.Credentials):
            raise AirflowFailException("static service-account key credentials are not accepted")
        return impersonated_credentials.Credentials(
            source_credentials=source_credentials,
            target_principal=target_principal,
            target_scopes=[_CLOUD_SCOPE],
            lifetime=900,
        )
    except AirflowFailException:
        raise
    except Exception as exc:
        raise AirflowFailException("keyless GCP credential setup failed") from exc


def _authorized_session():
    from google.auth.transport.requests import AuthorizedSession

    return AuthorizedSession(_impersonated_credentials())


def _verify_cloud_scheduler_is_inactive() -> dict[str, str]:
    """Require the GCP schedule to be paused or absent before Airflow invokes jobs."""
    resource = (
        f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{SCHEDULER_JOB}"
    )
    url = f"https://cloudscheduler.googleapis.com/v1/{resource}"
    response = _authorized_session().get(url, timeout=(10, 30))
    if response.status_code == 404:
        result = {"scheduler_job": resource, "scheduler_state": "ABSENT"}
        _LOGGER.info("DATAFORGE_AIRFLOW_WEATHER_SCHEDULER_PREFLIGHT %s", json.dumps(result))
        return result
    if response.status_code != 200:
        raise AirflowFailException(
            f"could not verify the GCP schedule is inactive (HTTP {response.status_code})"
        )
    try:
        state = response.json().get("state")
    except (AttributeError, ValueError) as exc:
        raise AirflowFailException("GCP schedule response was malformed") from exc
    if state != "PAUSED":
        raise AirflowFailException(
            "pause the GCP weather schedule before starting an Airflow cloud integration run"
        )
    result = {"scheduler_job": resource, "scheduler_state": "PAUSED"}
    _LOGGER.info("DATAFORGE_AIRFLOW_WEATHER_SCHEDULER_PREFLIGHT %s", json.dumps(result))
    return result


def _execute_cloud_run_job(job_name: str, args: list[str]) -> dict[str, str]:
    """Run one approved finite Cloud Run Job and return only execution identifiers."""
    if job_name not in _ALLOWED_JOB_NAMES:
        raise AirflowFailException("Cloud Run job is outside the approved Mini3 allowlist")
    if not args or any(not isinstance(value, str) for value in args):
        raise AirflowFailException("Cloud Run arguments must be a non-empty string list")

    session = _authorized_session()
    resource = f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{job_name}"
    run_url = f"https://run.googleapis.com/v2/{resource}:run"
    response = session.post(
        run_url,
        json={"overrides": {"containerOverrides": [{"args": args}]}},
        timeout=(10, 60),
    )
    if response.status_code not in {200, 201}:
        raise AirflowException(
            f"Cloud Run job start failed for {job_name} (HTTP {response.status_code})"
        )
    try:
        operation = response.json()
        operation_name = operation["name"]
    except (AttributeError, KeyError, ValueError) as exc:
        raise AirflowException("Cloud Run returned a malformed operation identity") from exc
    if not isinstance(operation_name, str) or not operation_name.startswith(
        f"projects/{PROJECT_ID}/locations/{REGION}/operations/"
    ):
        raise AirflowFailException("Cloud Run operation is outside the approved project/region")

    operation_url = f"https://run.googleapis.com/v2/{operation_name}"
    deadline = time.monotonic() + _CLOUD_RUN_POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        poll = session.get(operation_url, timeout=(10, 30))
        if poll.status_code != 200:
            raise AirflowException(
                f"Cloud Run operation read failed (HTTP {poll.status_code})"
            )
        try:
            operation_state = poll.json()
        except ValueError as exc:
            raise AirflowException("Cloud Run returned malformed operation state") from exc
        if operation_state.get("done") is True:
            if operation_state.get("error"):
                raise AirflowException(
                    f"Cloud Run job {job_name} failed; inspect its execution in Cloud Logging"
                )
            execution_name = operation_state.get("response", {}).get("name", "")
            if execution_name and not execution_name.startswith(
                f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{job_name}/executions/"
            ):
                raise AirflowFailException("Cloud Run execution identity is out of scope")
            result = {
                "job_name": job_name,
                "operation_name": operation_name,
                "execution_name": execution_name or operation_name,
            }
            _LOGGER.info("DATAFORGE_AIRFLOW_WEATHER_CLOUD_RUN %s", json.dumps(result))
            return result
        time.sleep(_CLOUD_RUN_POLL_SECONDS)
    raise AirflowException(
        f"Cloud Run job {job_name} exceeded the bounded operation wait"
    )


class GCSInvocationReceiptSensor(BaseSensorOperator):
    """Reschedule sensor for one immutable Mini3 invocation receipt in private GCS."""

    template_fields = ("invocation_id",)

    def __init__(
        self,
        *,
        invocation_id: str,
        bucket: str = BRONZE_BUCKET,
        **kwargs: Any,
    ) -> None:
        if bucket != BRONZE_BUCKET:
            raise ValueError("sensor bucket must match the approved private Bronze bucket")
        # Airflow merges DAG default_args into **kwargs before calling custom
        # operators; assign these values instead of passing duplicate keywords.
        kwargs.update(
            {
                "mode": "reschedule",
                "poke_interval": 20,
                "timeout": 20 * 60,
                "execution_timeout": timedelta(seconds=45),
                "exponential_backoff": True,
                "max_wait": 90,
            }
        )
        super().__init__(**kwargs)
        self.invocation_id = invocation_id
        self.bucket = bucket

    def poke(self, context: dict[str, Any]) -> bool:
        del context
        try:
            from google.api_core.exceptions import NotFound
            from google.cloud import storage

            client = storage.Client(
                project=PROJECT_ID,
                credentials=_impersonated_credentials(),
            )
            blob = client.bucket(self.bucket).blob(
                invocation_receipt_object(self.invocation_id)
            )
            blob.reload(timeout=30)
            return blob.generation is not None
        except NotFound:
            return False


@dag(
    dag_id=DAG_ID,
    description="Opt-in Airflow 3 controller for the real Mini-project 3 GCP weather pipeline.",
    schedule="0 9 * * *",
    start_date=pendulum.datetime(2026, 11, 1, 9, 0, tz=TIMEZONE),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=4,
    dagrun_timeout=timedelta(hours=2),
    is_paused_upon_creation=True,
    default_args={
        "owner": "dataforge-week7-reference",
        "depends_on_past": False,
        "retries": 1,
        "retry_delay": timedelta(seconds=30),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=3),
        "execution_timeout": timedelta(minutes=15),
        "on_failure_callback": local_failure_log,
    },
    tags=["dataforge", "week7", "mini3", "cloud-integration", "opt-in"],
)
def dataforge_week7_weather_cloud():
    """Run separate source, manifest, landing, dbt, publication and reconciliation stages."""

    @task(task_id="resolve_cloud_request", retries=0)
    def resolve_cloud_request() -> dict[str, Any]:
        context = get_current_context()
        dag_run = context["dag_run"]
        logical_date = context["logical_date"].in_timezone(TIMEZONE)
        latest_safe_date = pendulum.now(TIMEZONE).date() - timedelta(
            days=7
        )
        try:
            request = resolve_request(
                conf=getattr(dag_run, "conf", None) or {},
                dag_id=DAG_ID,
                run_id=dag_run.run_id,
                logical_date=logical_date,
                latest_safe_date=latest_safe_date,
            )
        except ContractError as exc:
            raise AirflowFailException(str(exc)) from exc
        _LOGGER.info(
            "DATAFORGE_AIRFLOW_WEATHER_REQUEST %s",
            json.dumps(
                {
                    "observation_date": request["observation_date"],
                    "provinces": request["provinces"],
                    "invocation_id": request["invocation_id"],
                    "source_settling_lag_days": 7,
                    "mode": "cloud_integration",
                },
                sort_keys=True,
            ),
        )
        return request

    @task(task_id="verify_gcp_schedule_paused", retries=0)
    def verify_gcp_schedule_paused() -> dict[str, str]:
        return _verify_cloud_scheduler_is_inactive()

    @task(task_id="execute_api_ingest", execution_timeout=_CLOUD_RUN_TASK_TIMEOUT)
    def execute_api_ingest(request: dict[str, Any]) -> dict[str, str]:
        return _execute_cloud_run_job(
            INGEST_JOB,
            [
                "ingest",
                "--observation-date",
                request["observation_date"],
                "--provinces",
                ",".join(PROVINCES),
                "--invocation-id",
                request["invocation_id"],
            ],
        )

    @task(task_id="read_execution_receipt")
    def read_execution_receipt(request: dict[str, Any]) -> dict[str, Any]:
        try:
            from google.cloud import storage

            client = storage.Client(
                project=PROJECT_ID,
                credentials=_impersonated_credentials(),
            )
            blob = client.bucket(BRONZE_BUCKET).blob(
                invocation_receipt_object(request["invocation_id"])
            )
            blob.reload(timeout=30)
            if blob.generation is None:
                raise AirflowFailException("GCS execution receipt has no object generation")
            generation = int(blob.generation)
            content = blob.download_as_text(
                if_generation_match=generation,
                timeout=30,
            )
            value = json.loads(content)
        except AirflowFailException:
            raise
        except Exception as exc:
            raise AirflowException("could not read the exact GCS execution receipt") from exc

        try:
            receipt = validate_execution_receipt(
                value,
                expected_invocation_id=request["invocation_id"],
                expected_observation_date=request["observation_date"],
                object_generation=generation,
            )
        except ContractError as exc:
            raise AirflowFailException(str(exc)) from exc
        _LOGGER.info(
            "DATAFORGE_AIRFLOW_WEATHER_MANIFEST %s",
            json.dumps(
                {
                    "request_id": receipt["request_id"],
                    "manifest_uri": receipt["manifest_uri"],
                    "manifest_generation": receipt["manifest_generation"],
                    "row_count": receipt["row_count"],
                },
                sort_keys=True,
            ),
        )
        return receipt

    @task(task_id="verify_landing_reconciliation", execution_timeout=_CLOUD_RUN_TASK_TIMEOUT)
    def verify_landing_reconciliation(receipt: dict[str, Any]) -> dict[str, str]:
        return _execute_cloud_run_job(
            INGEST_JOB,
            [
                "verify",
                "--request-id",
                receipt["request_id"],
                "--manifest-uri",
                receipt["manifest_uri"],
                "--manifest-generation",
                str(receipt["manifest_generation"]),
            ],
        )

    @task(task_id="load_bigquery_landing", execution_timeout=_CLOUD_RUN_TASK_TIMEOUT)
    def load_bigquery_landing(receipt: dict[str, Any]) -> dict[str, str]:
        return _execute_cloud_run_job(
            INGEST_JOB,
            [
                "land",
                "--manifest-uri",
                receipt["manifest_uri"],
                "--manifest-generation",
                str(receipt["manifest_generation"]),
            ],
        )

    @task(task_id="dbt_weather_build", execution_timeout=_CLOUD_RUN_TASK_TIMEOUT)
    def dbt_weather_build(request: dict[str, Any]) -> dict[str, str]:
        return _execute_cloud_run_job(
            DBT_JOB,
            [
                "build",
                "--target",
                "weather_prod",
                "--select",
                "tag:weather_mini3",
                "--vars",
                weather_dbt_vars_argument(request["observation_date"]),
            ],
        )

    @task(task_id="dbt_weather_test", execution_timeout=_CLOUD_RUN_TASK_TIMEOUT)
    def dbt_weather_test(request: dict[str, Any]) -> dict[str, str]:
        return _execute_cloud_run_job(
            DBT_JOB,
            [
                "test",
                "--target",
                "weather_prod",
                "--select",
                "tag:weather_mini3",
                "--vars",
                weather_dbt_vars_argument(request["observation_date"]),
            ],
        )

    @task(task_id="publish_weather_gold", execution_timeout=_CLOUD_RUN_TASK_TIMEOUT)
    def publish_weather_gold(request: dict[str, Any]) -> dict[str, str]:
        # dbt's SQL macro permits only simple identifiers; Airflow run IDs can
        # contain punctuation, so publish a stable, safe digest-based ID.
        workflow_run_id = f"airflow-{request['invocation_id'][:48]}"
        run_id_json = json.dumps(
            {"workflow_run_id": workflow_run_id},
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return _execute_cloud_run_job(
            DBT_JOB,
            [
                "run-operation",
                "publish_weather_mini3",
                "--target",
                "weather_prod",
                "--args",
                run_id_json,
            ],
        )

    @task(task_id="verify_published_gold")
    def verify_published_gold(request: dict[str, Any]) -> dict[str, Any]:
        try:
            from google.cloud import bigquery

            credentials = _impersonated_credentials()
            client = bigquery.Client(
                project=PROJECT_ID,
                credentials=credentials,
                location=REGION,
            )
            sql = f"""
                SELECT
                  COUNT(*) AS row_count,
                  COUNT(DISTINCT province_id) AS province_count,
                  COUNTIF(
                    precipitation_mm < 0
                    OR temp_max_c < -100
                    OR temp_max_c > 70
                  ) AS invalid_metric_rows
                FROM `{PROJECT_ID}.gold_weather_mini3.published_weather_daily`
                WHERE observation_date = @observation_date
            """
            job = client.query(
                sql,
                job_config=bigquery.QueryJobConfig(
                    maximum_bytes_billed=64 * 1024 * 1024,
                    query_parameters=[
                        bigquery.ScalarQueryParameter(
                            "observation_date",
                            "DATE",
                            request["observation_date"],
                        )
                    ],
                    labels={
                        "application": "dataforge",
                        "phase": "week7",
                        "action": "airflowweatherverify",
                    },
                ),
                location=REGION,
            )
            row = next(iter(job.result(timeout=180)))
        except Exception as exc:
            raise AirflowException("published weather Gold verification query failed") from exc

        result = {
            "query_job_id": job.job_id,
            "bytes_billed": int(job.total_bytes_billed or 0),
            "row_count": int(row["row_count"] or 0),
            "province_count": int(row["province_count"] or 0),
            "invalid_metric_rows": int(row["invalid_metric_rows"] or 0),
        }
        if (
            result["row_count"] != len(PROVINCES)
            or result["province_count"] != len(PROVINCES)
            or result["invalid_metric_rows"] != 0
        ):
            raise AirflowFailException(
                "published weather Gold does not reconcile to the 3-province daily contract"
            )
        return result

    @task(task_id="record_airflow_execution_receipt")
    def record_airflow_execution_receipt(
        request: dict[str, Any],
        scheduler_state: dict[str, str],
        manifest: dict[str, Any],
        ingest: dict[str, str],
        landing: dict[str, str],
        landing_reconciliation: dict[str, str],
        dbt_build: dict[str, str],
        dbt_test: dict[str, str],
        publish: dict[str, str],
        gold: dict[str, Any],
    ) -> dict[str, Any]:
        receipt = {
            "schema_version": "dataforge.weather.mini3.airflow-receipt.v1",
            "status": "PUBLISHED",
            "orchestrator": "local-docker-airflow-3.4.0",
            "dag_id": DAG_ID,
            "dag_run_id": request["dag_run_id"],
            "project_id": PROJECT_ID,
            "region": REGION,
            "gcp_scheduler_preflight": scheduler_state,
            "observation_date": request["observation_date"],
            "provinces": request["provinces"],
            "invocation_id": request["invocation_id"],
            "request_id": manifest["request_id"],
            "manifest_uri": manifest["manifest_uri"],
            "manifest_generation": manifest["manifest_generation"],
            "source_sha256": manifest["source_sha256"],
            "source_row_count": manifest["row_count"],
            "cloud_executions": {
                "ingest": ingest["execution_name"],
                "landing": landing["execution_name"],
                "landing_reconciliation": landing_reconciliation["execution_name"],
                "dbt_build": dbt_build["execution_name"],
                "dbt_test": dbt_test["execution_name"],
                "publish": publish["execution_name"],
            },
            "gold_verification": gold,
            "notification_scope": "Airflow local failure callback logs only",
        }
        encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        _LOGGER.info("DATAFORGE_AIRFLOW_WEATHER_RECEIPT %s", encoded)
        # Return only IDs, a few counts, and status through XCom; no rows or credentials.
        return {
            "status": receipt["status"],
            "dag_run_id": receipt["dag_run_id"],
            "request_id": receipt["request_id"],
            "manifest_uri": receipt["manifest_uri"],
            "manifest_generation": receipt["manifest_generation"],
            "gold_row_count": gold["row_count"],
            "gold_query_job_id": gold["query_job_id"],
        }

    request = resolve_cloud_request()
    scheduler_state = verify_gcp_schedule_paused()
    ingest = execute_api_ingest(request)
    scheduler_state >> ingest

    wait_for_invocation_receipt = GCSInvocationReceiptSensor(
        task_id="wait_for_gcs_invocation_receipt",
        invocation_id="{{ ti.xcom_pull(task_ids='resolve_cloud_request')['invocation_id'] }}",
        bucket=BRONZE_BUCKET,
    )
    request >> wait_for_invocation_receipt
    ingest >> wait_for_invocation_receipt

    manifest = read_execution_receipt(request)
    wait_for_invocation_receipt >> manifest
    landing = load_bigquery_landing(manifest)
    landing_reconciliation = verify_landing_reconciliation(manifest)
    build = dbt_weather_build(request)
    test = dbt_weather_test(request)
    publish = publish_weather_gold(request)
    gold = verify_published_gold(request)
    execution_receipt = record_airflow_execution_receipt(
        request,
        scheduler_state,
        manifest,
        ingest,
        landing,
        landing_reconciliation,
        build,
        test,
        publish,
        gold,
    )

    landing >> landing_reconciliation >> build >> test >> publish >> gold
    gold >> execution_receipt


dataforge_week7_weather_cloud()
