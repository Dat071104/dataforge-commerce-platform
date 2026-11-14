"""Opt-in Airflow 3 integration DAG for the Mini-project 3 weather slice.

Scheduled and manual dates come from validated Airflow Params. Cloud execution
also requires the independent DATAFORGE_WEATHER_CLOUD_ENABLED=true runtime
switch; the local fixture DAG remains isolated and unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import pendulum
from airflow.sdk import (
    BaseSensorOperator,
    DeadlineAlert,
    DeadlineReference,
    Param,
    SyncCallback,
    dag,
    get_current_context,
    task,
)
from airflow.sdk.bases.sensor import PokeReturnValue
from airflow.sdk.exceptions import AirflowException, AirflowFailException, AirflowSkipException
from dataforge_week7_weather_logic import (
    BRONZE_BUCKET,
    PROJECT_ID,
    PROVINCES,
    REGION,
    ContractError,
    ReceiptNotFound,
    cloud_opt_in_enabled,
    invocation_receipt_object,
    is_retryable_cloud_operation_error,
    is_retryable_http_status,
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
_CLOUD_RUN_SENSOR_TIMEOUT_SECONDS = 35 * 60
_CLOUD_RUN_SENSOR_POKE_INTERVAL_SECONDS = 60
_CLOUD_RUN_SUBMISSION_POOL = "cloud_run_submissions"
_CLOUD_RUN_POLL_SECONDS = 10
_CLOUD_RUN_POLL_TIMEOUT_SECONDS = 35 * 60
_CLOUD_RUN_POLL_TRANSIENT_RETRIES = 2
_CLOUD_RUN_OPERATION_PREFIX = f"projects/{PROJECT_ID}/locations/{REGION}/operations/"
_ALLOWED_JOB_NAMES = {INGEST_JOB, DBT_JOB}
_IDENTITY_MODE_ADC_FILE = "impersonated_adc"
_IDENTITY_MODE_ATTACHED = "attached_service_account"
_AIRFLOW_CALLER = re.compile(
    rf"^dataforge-week7-airflow@{re.escape(PROJECT_ID)}\.iam\.gserviceaccount\.com$"
)


def _require_cloud_authorization() -> str:
    """Enforce the opt-in, fixed target, and an explicit credential mode."""
    try:
        enabled = cloud_opt_in_enabled(os.environ.get("DATAFORGE_WEATHER_CLOUD_ENABLED"))
    except ContractError as exc:
        raise AirflowFailException(str(exc)) from exc
    if not enabled:
        raise AirflowSkipException(
            "DISABLED: cloud execution is off; this scheduled/manual run made no cloud API calls"
        )

    configured_project = os.environ.get("DATAFORGE_WEATHER_PROJECT_ID", PROJECT_ID)
    configured_region = os.environ.get("DATAFORGE_WEATHER_REGION", REGION)
    if configured_project != PROJECT_ID or configured_region != REGION:
        raise AirflowFailException("cloud execution target is outside the approved project/region")
    identity_mode = os.environ.get(
        "DATAFORGE_AIRFLOW_IDENTITY_MODE",
        _IDENTITY_MODE_ADC_FILE,
    ).strip()
    if identity_mode == _IDENTITY_MODE_ADC_FILE:
        target_principal = os.environ.get("DATAFORGE_AIRFLOW_IMPERSONATION_SERVICE_ACCOUNT", "")
        if not _AIRFLOW_CALLER.fullmatch(target_principal):
            raise AirflowFailException("the configured Airflow impersonation target is not approved")
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") != GOOGLE_APPLICATION_CREDENTIALS_PATH:
            raise AirflowFailException("impersonated ADC mode requires the explicit ADC file mount")
        if not os.path.isfile(GOOGLE_APPLICATION_CREDENTIALS_PATH):
            raise AirflowFailException("the explicit keyless ADC file is unavailable")
        if os.environ.get("DATAFORGE_AIRFLOW_ATTACHED_SERVICE_ACCOUNT"):
            raise AirflowFailException("ADC-file and attached identity settings cannot be combined")
        return identity_mode

    if identity_mode == _IDENTITY_MODE_ATTACHED:
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            raise AirflowFailException("attached identity mode forbids GOOGLE_APPLICATION_CREDENTIALS")
        if os.environ.get("DATAFORGE_AIRFLOW_IMPERSONATION_SERVICE_ACCOUNT"):
            raise AirflowFailException("attached identity mode does not accept an impersonation target")
        attached_principal = os.environ.get("DATAFORGE_AIRFLOW_ATTACHED_SERVICE_ACCOUNT", "")
        if not _AIRFLOW_CALLER.fullmatch(attached_principal):
            raise AirflowFailException("the configured attached Airflow identity is not approved")
        return identity_mode

    raise AirflowFailException("DATAFORGE_AIRFLOW_IDENTITY_MODE is unsupported")


def local_failure_log(context: dict[str, Any]) -> None:
    """Log redacted Airflow failure metadata; this is not external delivery."""
    task_instance = context.get("task_instance")
    dag_run = context.get("dag_run")
    exception = context.get("exception")
    receipt = {
        "event_type": "PIPELINE_FAILED",
        "terminal_state": "FAILED",
        "dag_id": getattr(dag_run, "dag_id", None),
        "workflow_run_id": getattr(dag_run, "run_id", None),
        "task_id": getattr(task_instance, "task_id", None),
        "try_number": getattr(task_instance, "try_number", None),
        "error_class": type(exception).__name__ if exception is not None else None,
        "event_destination": "local_airflow_log_only",
        "external_notification_sent": False,
    }
    _LOGGER.error("DATAFORGE_AIRFLOW_WEATHER_FAILURE %s", json.dumps(receipt, sort_keys=True))


def local_deadline_log(**kwargs: Any) -> None:
    """Log a redacted DagRun deadline event; this does not deliver a notification."""
    context = kwargs.get("context")
    if context is None:
        context = kwargs

    def value(item: Any, key: str) -> Any:
        if isinstance(item, Mapping):
            return item.get(key)
        return getattr(item, key, None)

    dag_run = value(context, "dag_run")
    deadline = value(context, "deadline")
    receipt = {
        "event_type": "PIPELINE_DEADLINE_MISSED",
        "dag_id": value(dag_run, "dag_id"),
        "workflow_run_id": value(dag_run, "run_id") or value(dag_run, "dag_run_id"),
        "deadline_time": str(value(deadline, "deadline_time") or "") or None,
        "event_destination": "local_airflow_log_only",
        "external_notification_sent": False,
    }
    _LOGGER.error("DATAFORGE_AIRFLOW_WEATHER_DEADLINE %s", json.dumps(receipt, sort_keys=True))


def _authorized_credentials():
    """Load either the legacy impersonated ADC source or the attached VM identity."""
    identity_mode = _require_cloud_authorization()
    try:
        import google.auth
        from google.auth import impersonated_credentials
        from google.auth.compute_engine import credentials as compute_engine_credentials
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        source_credentials, _ = google.auth.default(scopes=[_CLOUD_SCOPE])
        if identity_mode == _IDENTITY_MODE_ATTACHED:
            if not isinstance(source_credentials, compute_engine_credentials.Credentials):
                raise AirflowFailException(
                    "attached identity mode requires Compute Engine metadata credentials"
                )
            source_credentials.refresh(Request())
            attached_principal = source_credentials.service_account_email
            expected_principal = os.environ.get("DATAFORGE_AIRFLOW_ATTACHED_SERVICE_ACCOUNT", "")
            if attached_principal != expected_principal:
                raise AirflowFailException(
                    "the metadata server principal does not match the approved attached identity"
                )
            return source_credentials

        if isinstance(source_credentials, service_account.Credentials):
            raise AirflowFailException("static service-account key credentials are not accepted")
        return impersonated_credentials.Credentials(
            source_credentials=source_credentials,
            target_principal=os.environ["DATAFORGE_AIRFLOW_IMPERSONATION_SERVICE_ACCOUNT"],
            target_scopes=[_CLOUD_SCOPE],
            lifetime=900,
        )
    except AirflowFailException:
        raise
    except Exception as exc:
        raise AirflowFailException("keyless GCP credential setup failed") from exc


def _authorized_session():
    from google.auth.transport.requests import AuthorizedSession

    return AuthorizedSession(_authorized_credentials())


def _raise_cloud_http_failure(action: str, status_code: int) -> None:
    message = f"{action} failed (HTTP {status_code})"
    if is_retryable_http_status(status_code):
        raise AirflowException(message)
    raise AirflowFailException(message)


def _submit_cloud_run_job(job_name: str, args: list[str]) -> str:
    """Submit an allowlisted Cloud Run job and return its operation name immediately."""
    if job_name not in _ALLOWED_JOB_NAMES:
        raise AirflowFailException("Cloud Run job is outside the approved Mini3 allowlist")
    if not args or any(not isinstance(value, str) for value in args):
        raise AirflowFailException("Cloud Run arguments must be a non-empty string list")

    resource = f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{job_name}"
    run_url = f"https://run.googleapis.com/v2/{resource}:run"
    try:
        from google.auth.exceptions import GoogleAuthError
        from requests.exceptions import RequestException

        response = _authorized_session().post(
            run_url,
            json={"overrides": {"containerOverrides": [{"args": args}]}},
            timeout=(10, 60),
        )
    except RequestException as exc:
        # The API has no caller-supplied idempotency token. A retry keeps the
        # invocation ID stable but may create a duplicate Cloud Run execution.
        raise AirflowException(
            "Cloud Run job start had a transient transport failure; inspect the receipt before replay"
        ) from exc
    except GoogleAuthError as exc:
        raise AirflowFailException("Cloud Run credentials or impersonation failed") from exc
    if response.status_code not in {200, 201}:
        _raise_cloud_http_failure(f"Cloud Run job start for {job_name}", response.status_code)
    try:
        operation = response.json()
        operation_name = operation["name"]
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise AirflowFailException("Cloud Run returned a malformed operation identity") from exc
    if not isinstance(operation, dict):
        raise AirflowFailException("Cloud Run operation response is not a JSON object")
    if (
        not isinstance(operation_name, str)
        or not operation_name.startswith(_CLOUD_RUN_OPERATION_PREFIX)
        or not operation_name.removeprefix(_CLOUD_RUN_OPERATION_PREFIX)
        or "/" in operation_name.removeprefix(_CLOUD_RUN_OPERATION_PREFIX)
    ):
        raise AirflowFailException("Cloud Run operation is outside the approved project/region")

    _LOGGER.info(
        "DATAFORGE_AIRFLOW_WEATHER_CLOUD_RUN_SUBMITTED %s",
        json.dumps({"job_name": job_name, "operation_name": operation_name}, sort_keys=True),
    )
    return operation_name


def _raise_google_api_failure(action: str, error: Exception) -> None:
    """Map Google API transport/service errors to bounded Airflow retry classes."""
    from google.api_core.exceptions import (
        DeadlineExceeded,
        GatewayTimeout,
        GoogleAPICallError,
        InternalServerError,
        RetryError,
        ServiceUnavailable,
        TooManyRequests,
    )
    from requests.exceptions import RequestException

    message = f"{action} failed; inspect the task log for its redacted contract status"
    if isinstance(
        error,
        (
            DeadlineExceeded,
            GatewayTimeout,
            InternalServerError,
            RetryError,
            ServiceUnavailable,
            TooManyRequests,
            RequestException,
        ),
    ):
        raise AirflowException(message) from error
    if isinstance(error, GoogleAPICallError):
        raise AirflowFailException(message) from error
    raise AirflowFailException(f"{action} failed with a terminal configuration or contract error") from error


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
        _raise_cloud_http_failure("GCP schedule inactivity check", response.status_code)
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
    try:
        from google.auth.exceptions import GoogleAuthError
        from requests.exceptions import RequestException

        response = session.post(
            run_url,
            json={"overrides": {"containerOverrides": [{"args": args}]}},
            timeout=(10, 60),
        )
    except RequestException as exc:
        # Cloud Run's run endpoint has no caller-supplied idempotency token. The
        # Airflow retry reuses the same invocation/run identity, so committed
        # data is replay safe, but the service may have accepted the prior POST.
        raise AirflowException(
            "Cloud Run job start had a transient transport failure; retry uses the stable run identity"
        ) from exc
    except GoogleAuthError as exc:
        raise AirflowFailException("Cloud Run credentials or impersonation failed") from exc
    except AirflowFailException:
        raise
    if response.status_code not in {200, 201}:
        _raise_cloud_http_failure(f"Cloud Run job start for {job_name}", response.status_code)
    try:
        operation = response.json()
        operation_name = operation["name"]
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise AirflowFailException("Cloud Run returned a malformed operation identity") from exc
    if not isinstance(operation, dict):
        raise AirflowFailException("Cloud Run operation response is not a JSON object")
    if (
        not isinstance(operation_name, str)
        or not operation_name.startswith(_CLOUD_RUN_OPERATION_PREFIX)
        or not operation_name.removeprefix(_CLOUD_RUN_OPERATION_PREFIX)
        or "/" in operation_name.removeprefix(_CLOUD_RUN_OPERATION_PREFIX)
    ):
        raise AirflowFailException("Cloud Run operation is outside the approved project/region")

    operation_url = f"https://run.googleapis.com/v2/{operation_name}"
    deadline = time.monotonic() + _CLOUD_RUN_POLL_TIMEOUT_SECONDS
    transient_poll_failures = 0
    while time.monotonic() < deadline:
        try:
            from google.auth.exceptions import GoogleAuthError
            from requests.exceptions import RequestException

            poll = session.get(operation_url, timeout=(10, 30))
        except RequestException as exc:
            transient_poll_failures += 1
            if transient_poll_failures > _CLOUD_RUN_POLL_TRANSIENT_RETRIES:
                raise AirflowFailException(
                    "Cloud Run operation polling exhausted bounded transport retries; inspect the execution before replay"
                ) from exc
            time.sleep(min(_CLOUD_RUN_POLL_SECONDS, 2**transient_poll_failures))
            continue
        except GoogleAuthError as exc:
            raise AirflowFailException("Cloud Run credentials or impersonation failed while polling") from exc
        if poll.status_code != 200:
            if is_retryable_http_status(poll.status_code):
                transient_poll_failures += 1
                if transient_poll_failures > _CLOUD_RUN_POLL_TRANSIENT_RETRIES:
                    raise AirflowFailException(
                        "Cloud Run operation polling exhausted bounded HTTP retries; inspect the execution before replay"
                    )
                time.sleep(min(_CLOUD_RUN_POLL_SECONDS, 2**transient_poll_failures))
                continue
            _raise_cloud_http_failure("Cloud Run operation read", poll.status_code)
        transient_poll_failures = 0
        try:
            operation_state = poll.json()
        except (AttributeError, ValueError) as exc:
            raise AirflowFailException("Cloud Run returned malformed operation state") from exc
        if not isinstance(operation_state, dict):
            raise AirflowFailException("Cloud Run operation state is not a JSON object")
        if not isinstance(operation_state.get("done"), bool):
            raise AirflowFailException("Cloud Run operation state has no boolean done flag")
        if operation_state.get("done") is True:
            if operation_state.get("error"):
                if is_retryable_cloud_operation_error(operation_state["error"]):
                    raise AirflowException(
                        f"Cloud Run job {job_name} failed with a transient operation status; retry uses the stable run identity"
                    )
                raise AirflowFailException(
                    f"Cloud Run job {job_name} failed with a terminal operation status; inspect its execution in Cloud Logging"
                )
            execution_response = operation_state.get("response")
            if not isinstance(execution_response, dict):
                raise AirflowFailException("Cloud Run completion response is malformed")
            execution_name = execution_response.get("name", "")
            expected_execution_prefix = (
                f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{job_name}/executions/"
            )
            if (
                not isinstance(execution_name, str)
                or not execution_name.startswith(expected_execution_prefix)
                or not execution_name.removeprefix(expected_execution_prefix)
                or "/" in execution_name.removeprefix(expected_execution_prefix)
            ):
                raise AirflowFailException("Cloud Run execution identity is out of scope")
            result = {
                "job_name": job_name,
                "operation_name": operation_name,
                "execution_name": execution_name,
            }
            _LOGGER.info("DATAFORGE_AIRFLOW_WEATHER_CLOUD_RUN %s", json.dumps(result))
            return result
        time.sleep(_CLOUD_RUN_POLL_SECONDS)
    raise AirflowFailException(
        f"Cloud Run job {job_name} exceeded the bounded operation wait; inspect the execution before replay"
    )


class CloudRunExecutionReceiptSensor(BaseSensorOperator):
    """Reschedule while an allowlisted Cloud Run execution and optional receipt complete."""

    template_fields = ("job_name", "operation_name", "request")

    def __init__(
        self,
        *,
        job_name: str,
        operation_name: str,
        request: dict[str, Any] | None = None,
        require_receipt: bool = False,
        **kwargs: Any,
    ) -> None:
        self.job_name = job_name
        self.operation_name = operation_name
        self.request = request
        self.require_receipt = require_receipt
        super().__init__(**kwargs)

    def poke(self, context: dict[str, Any]) -> bool | PokeReturnValue:
        if self.job_name not in _ALLOWED_JOB_NAMES:
            raise AirflowFailException("Cloud Run job is outside the approved Mini3 allowlist")
        operation_name = self.operation_name
        if (
            not isinstance(operation_name, str)
            or not operation_name.startswith(_CLOUD_RUN_OPERATION_PREFIX)
            or not operation_name.removeprefix(_CLOUD_RUN_OPERATION_PREFIX)
            or "/" in operation_name.removeprefix(_CLOUD_RUN_OPERATION_PREFIX)
        ):
            raise AirflowFailException("Cloud Run operation identity is outside the approved project/region")

        session = _authorized_session()
        operation_url = f"https://run.googleapis.com/v2/{operation_name}"
        operation_response = session.get(operation_url, timeout=(10, 30))
        if operation_response.status_code != 200:
            _raise_cloud_http_failure("Cloud Run operation read", operation_response.status_code)
        try:
            operation_state = operation_response.json()
        except (AttributeError, TypeError, ValueError) as exc:
            raise AirflowFailException("Cloud Run returned malformed operation state") from exc
        if not isinstance(operation_state, dict) or not isinstance(operation_state.get("done"), bool):
            raise AirflowFailException("Cloud Run operation state has no boolean done flag")
        if operation_state["done"] is False:
            return False
        if operation_state.get("error"):
            if is_retryable_cloud_operation_error(operation_state["error"]):
                raise AirflowException("Cloud Run operation failed with a retryable status")
            raise AirflowFailException("Cloud Run operation failed with a terminal status")

        operation_result = operation_state.get("response")
        if not isinstance(operation_result, dict):
            raise AirflowFailException("Cloud Run operation response is malformed")
        execution_name = operation_result.get("name", "")
        expected_execution_prefix = (
            f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{self.job_name}/executions/"
        )
        execution_id = (
            execution_name.removeprefix(expected_execution_prefix)
            if isinstance(execution_name, str)
            else ""
        )
        if (
            not isinstance(execution_name, str)
            or not execution_name.startswith(expected_execution_prefix)
            or not execution_id
            or "/" in execution_id
        ):
            raise AirflowFailException("Cloud Run execution identity is outside the approved job")

        execution_url = f"https://run.googleapis.com/v2/{execution_name}"
        execution_response = session.get(execution_url, timeout=(10, 30))
        if execution_response.status_code == 404:
            # The operation may complete just before the execution becomes
            # visible through the GetExecution endpoint.
            return False
        if execution_response.status_code != 200:
            _raise_cloud_http_failure("Cloud Run execution read", execution_response.status_code)
        try:
            execution = execution_response.json()
        except (AttributeError, TypeError, ValueError) as exc:
            raise AirflowFailException("Cloud Run returned malformed execution state") from exc
        if not isinstance(execution, dict):
            raise AirflowFailException("Cloud Run execution state is not a JSON object")
        completion_status = execution.get("completionStatus")
        if completion_status in {"EXECUTION_FAILED", "EXECUTION_CANCELLED"}:
            raise AirflowFailException(
                f"Cloud Run execution reached terminal status {completion_status}"
            )
        if completion_status != "EXECUTION_SUCCEEDED":
            return False

        result: dict[str, Any] = {"execution_name": execution_name}
        if self.require_receipt:
            if not isinstance(self.request, dict):
                raise AirflowFailException("receipt sensor is missing the resolved Cloud Run request")
            invocation_id = self.request.get("invocation_id")
            try:
                object_name = invocation_receipt_object(invocation_id)
            except (ContractError, TypeError) as exc:
                raise AirflowFailException("receipt sensor received an invalid invocation ID") from exc
            receipt_url = (
                "https://storage.googleapis.com/storage/v1/b/"
                f"{BRONZE_BUCKET}/o/{quote(object_name, safe='')}?fields=generation"
            )
            receipt_response = session.get(receipt_url, timeout=(10, 30))
            if receipt_response.status_code == 404:
                return False
            if receipt_response.status_code != 200:
                _raise_cloud_http_failure("GCS invocation receipt metadata read", receipt_response.status_code)
            try:
                receipt_metadata = receipt_response.json()
                generation = int(receipt_metadata["generation"])
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                raise AirflowFailException("GCS invocation receipt metadata is malformed") from exc
            if generation <= 0:
                raise AirflowFailException("GCS invocation receipt generation must be positive")
            result["receipt_generation"] = generation

        _LOGGER.info(
            "DATAFORGE_AIRFLOW_WEATHER_EXECUTION_READY %s",
            json.dumps(result, sort_keys=True),
        )
        return PokeReturnValue(is_done=True, xcom_value=result)


def _read_cloud_execution_receipt(
    request: dict[str, Any], expected_generation: int
) -> tuple[dict[str, Any], int]:
    """Read and validate the exact immutable receipt generation observed by the sensor."""
    if isinstance(expected_generation, bool) or not isinstance(expected_generation, int):
        raise AirflowFailException("GCS receipt sensor did not provide a valid generation")
    if expected_generation <= 0:
        raise AirflowFailException("GCS receipt sensor generation must be positive")
    try:
        from google.api_core.exceptions import (
            DeadlineExceeded,
            GatewayTimeout,
            GoogleAPICallError,
            InternalServerError,
            NotFound,
            RetryError,
            ServiceUnavailable,
            TooManyRequests,
        )
        from google.cloud import storage
        from requests.exceptions import RequestException

        client = storage.Client(
            project=PROJECT_ID,
            credentials=_authorized_credentials(),
        )
        blob = client.bucket(BRONZE_BUCKET).blob(
            invocation_receipt_object(request["invocation_id"])
        )
    except (AirflowFailException, AirflowSkipException):
        raise
    except Exception as exc:
        raise AirflowFailException("keyless GCS receipt client setup failed") from exc

    def read_exact_object() -> tuple[dict[str, Any], int]:
        try:
            blob.reload(timeout=30)
        except NotFound as exc:
            raise ReceiptNotFound from exc
        except (DeadlineExceeded, GatewayTimeout, InternalServerError, RetryError,
                ServiceUnavailable, TooManyRequests, RequestException) as exc:
            raise AirflowException("transient error while reading the GCS execution receipt") from exc
        except GoogleAPICallError as exc:
            raise AirflowFailException("GCS execution receipt read was rejected") from exc

        if blob.generation is None:
            raise AirflowFailException("GCS execution receipt has no object generation")
        try:
            generation = int(blob.generation)
        except (TypeError, ValueError) as exc:
            raise AirflowFailException("GCS execution receipt generation is malformed") from exc
        if generation != expected_generation:
            raise AirflowFailException(
                "GCS execution receipt generation changed after the sensor observed it"
            )
        try:
            content = blob.download_as_text(
                if_generation_match=generation,
                timeout=30,
            )
            value = json.loads(content)
        except (DeadlineExceeded, GatewayTimeout, InternalServerError, RetryError,
                ServiceUnavailable, TooManyRequests, RequestException) as exc:
            raise AirflowException("transient error while downloading the GCS execution receipt") from exc
        except GoogleAPICallError as exc:
            raise AirflowFailException("exact-generation GCS receipt download was rejected") from exc
        except (TypeError, ValueError) as exc:
            raise AirflowFailException("GCS execution receipt is not valid JSON") from exc
        return value, generation

    try:
        return read_exact_object()
    except ReceiptNotFound as exc:
        raise AirflowFailException("GCS execution receipt disappeared after sensor success") from exc
    except ContractError as exc:
        raise AirflowFailException(str(exc)) from exc


@dag(
    dag_id=DAG_ID,
    description="Opt-in Airflow 3 controller for the real Mini-project 3 GCP weather pipeline.",
    doc_md=(
        "## Mini3 weather controller\n"
        "Runs daily at 09:00 in `Asia/Ho_Chi_Minh`. Scheduled observation date is "
        "`data_interval_end` minus the seven-day settling lag; manual runs may select an "
        "allowed settled date. Cloud execution remains opt-in and this DAG is paused on creation.\n\n"
        "The DagRun uses an experimental Airflow 3 Deadline Alert 90 minutes after queueing. "
        "Airflow 3 removed legacy SLA callbacks; the deadline callback emits one redacted, "
        "local-log-only `PIPELINE_DEADLINE_MISSED` event."
    ),
    schedule="0 9 * * *",
    start_date=pendulum.datetime(2026, 11, 1, 9, 0, tz=TIMEZONE),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=4,
    dagrun_timeout=timedelta(hours=2),
    deadline=DeadlineAlert(
        reference=DeadlineReference.DAGRUN_QUEUED_AT,
        interval=timedelta(minutes=90),
        callback=SyncCallback(local_deadline_log),
    ),
    is_paused_upon_creation=True,
    params={
        "mode": Param("scheduled", type="string", enum=["scheduled", "manual"]),
        "observation_date": Param(
            None,
            type=["null", "string"],
            pattern=r"^\d{4}-\d{2}-\d{2}$",
        ),
    },
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

    @task(
        task_id="resolve_cloud_request",
        retries=0,
        doc_md=(
            "Resolves the fixed Airflow logical date and interval end. Scheduled runs use "
            "`data_interval_end - 7 days`; retries reuse the same DagRun identity."
        ),
    )
    def resolve_cloud_request() -> dict[str, Any]:
        context = get_current_context()
        dag_run = context["dag_run"]
        logical_date = context["logical_date"].in_timezone(TIMEZONE)
        data_interval_end = context["data_interval_end"].in_timezone(TIMEZONE)
        try:
            request = resolve_request(
                params=context.get("params", {}),
                dag_id=DAG_ID,
                run_id=dag_run.run_id,
                logical_date=logical_date,
                data_interval_end=data_interval_end,
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
                    "mode": request["mode"],
                },
                sort_keys=True,
            ),
        )
        return request

    @task(task_id="authorize_cloud_execution", retries=0)
    def authorize_cloud_execution(request: dict[str, Any]) -> dict[str, str]:
        try:
            _require_cloud_authorization()
        except AirflowSkipException:
            _LOGGER.info(
                "DATAFORGE_AIRFLOW_WEATHER_NO_OP %s",
                json.dumps(
                    {
                        "status": "DISABLED",
                        "mode": request["mode"],
                        "observation_date": request["observation_date"],
                        "invocation_id": request["invocation_id"],
                        "reason": "DATAFORGE_WEATHER_CLOUD_ENABLED is false or unset",
                    },
                    sort_keys=True,
                ),
            )
            raise
        result = {
            "status": "AUTHORIZED",
            "project_id": PROJECT_ID,
            "region": REGION,
        }
        _LOGGER.info("DATAFORGE_AIRFLOW_WEATHER_AUTHORIZED %s", json.dumps(result))
        return result

    @task(task_id="verify_gcp_schedule_paused", retries=1)
    def verify_gcp_schedule_paused() -> dict[str, str]:
        return _verify_cloud_scheduler_is_inactive()

    @task(
        task_id="execute_api_ingest",
        execution_timeout=timedelta(minutes=2),
        pool=_CLOUD_RUN_SUBMISSION_POOL,
        doc_md=(
            "Submits the allowlisted ingest job and returns the Cloud Run operation name. "
            "The separate `wait_for_api_ingest` sensor reschedules while the execution and "
            "immutable invocation receipt complete."
        ),
    )
    def execute_api_ingest(request: dict[str, Any]) -> str:
        return _submit_cloud_run_job(
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

    @task(
        task_id="read_execution_receipt",
        doc_md=(
            "Reads and validates the exact receipt generation already observed by the "
            "reschedule sensor. The generation precondition fails closed if the object changes."
        ),
    )
    def read_execution_receipt(
        request: dict[str, Any], ingest_state: dict[str, Any]
    ) -> dict[str, Any]:
        value, generation = _read_cloud_execution_receipt(
            request,
            expected_generation=ingest_state.get("receipt_generation"),
        )

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

    @task(
        task_id="verify_landing_reconciliation",
        execution_timeout=timedelta(minutes=2),
        pool=_CLOUD_RUN_SUBMISSION_POOL,
        doc_md="Submits the landing reconciliation job and returns its Cloud Run operation name.",
    )
    def verify_landing_reconciliation(receipt: dict[str, Any]) -> str:
        return _submit_cloud_run_job(
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

    @task(
        task_id="load_bigquery_landing",
        execution_timeout=timedelta(minutes=2),
        pool=_CLOUD_RUN_SUBMISSION_POOL,
        doc_md="Submits the landing load job and returns its Cloud Run operation name.",
    )
    def load_bigquery_landing(receipt: dict[str, Any]) -> str:
        return _submit_cloud_run_job(
            INGEST_JOB,
            [
                "land",
                "--manifest-uri",
                receipt["manifest_uri"],
                "--manifest-generation",
                str(receipt["manifest_generation"]),
            ],
        )

    @task(
        task_id="dbt_weather_build",
        execution_timeout=timedelta(minutes=2),
        pool=_CLOUD_RUN_SUBMISSION_POOL,
        doc_md="Submits the offline-tested, allowlisted dbt weather build job and returns its operation name.",
    )
    def dbt_weather_build(request: dict[str, Any]) -> str:
        return _submit_cloud_run_job(
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

    @task(
        task_id="publish_weather_gold",
        execution_timeout=timedelta(minutes=2),
        pool=_CLOUD_RUN_SUBMISSION_POOL,
        doc_md="Submits the guarded Gold publication job and returns its Cloud Run operation name.",
    )
    def publish_weather_gold(request: dict[str, Any]) -> str:
        # dbt's SQL macro permits only simple identifiers; Airflow run IDs can
        # contain punctuation, so publish a stable, safe digest-based ID.
        workflow_run_id = f"airflow-{request['invocation_id'][:48]}"
        run_id_json = json.dumps(
            {"workflow_run_id": workflow_run_id},
            ensure_ascii=True,
            separators=(",", ":"),
        )
        return _submit_cloud_run_job(
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

            credentials = _authorized_credentials()
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
            _raise_google_api_failure("published weather Gold verification query", exc)

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

    def wait_for_cloud_run(
        *,
        task_id: str,
        job_name: str,
        operation_name: str,
        request_value: dict[str, Any] | None = None,
        require_receipt: bool = False,
    ) -> CloudRunExecutionReceiptSensor:
        return CloudRunExecutionReceiptSensor(
            task_id=task_id,
            job_name=job_name,
            operation_name=operation_name,
            request=request_value,
            require_receipt=require_receipt,
            mode="reschedule",
            poke_interval=_CLOUD_RUN_SENSOR_POKE_INTERVAL_SECONDS,
            timeout=_CLOUD_RUN_SENSOR_TIMEOUT_SECONDS,
            execution_timeout=_CLOUD_RUN_TASK_TIMEOUT,
            retries=0,
            do_xcom_push=True,
            doc_md=(
                "Releases its worker slot between polls. Checks the Cloud Run operation and "
                "Execution state; the ingest sensor also waits for the immutable GCS receipt."
            ),
        )

    request = resolve_cloud_request()
    authorization = authorize_cloud_execution(request)
    scheduler_state = verify_gcp_schedule_paused()
    ingest_operation = execute_api_ingest(request)
    ingest_sensor = wait_for_cloud_run(
        task_id="wait_for_api_ingest",
        job_name=INGEST_JOB,
        operation_name=ingest_operation,
        request_value=request,
        require_receipt=True,
    )
    ingest = ingest_sensor.output
    scheduler_state >> ingest_operation
    authorization >> scheduler_state

    manifest = read_execution_receipt(request, ingest)
    landing_operation = load_bigquery_landing(manifest)
    landing_sensor = wait_for_cloud_run(
        task_id="wait_for_bigquery_landing",
        job_name=INGEST_JOB,
        operation_name=landing_operation,
    )
    landing = landing_sensor.output
    reconciliation_operation = verify_landing_reconciliation(manifest)
    reconciliation_sensor = wait_for_cloud_run(
        task_id="wait_for_landing_reconciliation",
        job_name=INGEST_JOB,
        operation_name=reconciliation_operation,
    )
    landing_reconciliation = reconciliation_sensor.output
    build_operation = dbt_weather_build(request)
    build_sensor = wait_for_cloud_run(
        task_id="wait_for_dbt_weather_build",
        job_name=DBT_JOB,
        operation_name=build_operation,
    )
    build = build_sensor.output
    publish_operation = publish_weather_gold(request)
    publish_sensor = wait_for_cloud_run(
        task_id="wait_for_publish_weather_gold",
        job_name=DBT_JOB,
        operation_name=publish_operation,
    )
    publish = publish_sensor.output
    gold = verify_published_gold(request)
    execution_receipt = record_airflow_execution_receipt(
        request,
        scheduler_state,
        manifest,
        ingest,
        landing,
        landing_reconciliation,
        build,
        publish,
        gold,
    )

    landing >> reconciliation_operation >> landing_reconciliation >> build_operation
    build >> publish_operation >> publish >> gold
    gold >> execution_receipt


dataforge_week7_weather_cloud()
