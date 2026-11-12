"""Local-only Airflow 3.x reference for the Week-7 orchestration stages.

The default run is a successful NO_NEW_BATCH path. ``local_fixture`` runs a
small checked-in example through the orchestration contract, but never executes
dbt, connects to GCP, or writes a publication pointer. The failure callback
logs redacted run metadata only; no email, webhook, or other notification is
configured.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

import pendulum
from airflow.sdk import dag, get_current_context, task
from airflow.sdk.exceptions import AirflowException, AirflowFailException
from dataforge_week7_logic import (
    FIXTURE_PATH,
    build_local_manifest,
    consume_local_silver,
    publication_fence,
    transform_local_silver,
    validate_local_transformation,
)

DAG_ID = "dataforge_week7_local_reference"
_LOGGER = logging.getLogger("airflow.task")


def local_failure_alert(context: dict) -> None:
    """Log a redacted alert receipt without calling an external notification sink."""
    task_instance = context.get("task_instance")
    dag_run = context.get("dag_run")
    exception = context.get("exception")
    receipt = {
        "hook": "LOCAL_LOG_ONLY",
        "dag_id": getattr(dag_run, "dag_id", None),
        "run_id": getattr(dag_run, "run_id", None),
        "task_id": getattr(task_instance, "task_id", None),
        "try_number": getattr(task_instance, "try_number", None),
        "exception_type": type(exception).__name__ if exception is not None else None,
    }
    _LOGGER.error("DATAFORGE_AIRFLOW_FAILURE_ALERT %s", json.dumps(receipt, sort_keys=True))


@dag(
    dag_id=DAG_ID,
    description="Local-only Week-7 pipeline orchestration contract; no cloud writes.",
    schedule="0 6 * * *",
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=15),
    default_args={
        "owner": "dataforge-local-reference",
        "retries": 1,
        "retry_delay": timedelta(seconds=5),
        "execution_timeout": timedelta(minutes=3),
        "on_failure_callback": local_failure_alert,
    },
    tags=["dataforge", "week7", "local-only"],
)
def dataforge_week7_local_reference():
    """Model manifest -> Silver -> dbt -> quality -> publication/recovery flow."""

    @task(task_id="resolve_manifest")
    def resolve_manifest() -> dict:
        context = get_current_context()
        dag_run = context.get("dag_run")
        conf = getattr(dag_run, "conf", None) or {}
        ti = context["ti"]
        logical_date = getattr(dag_run, "logical_date", None)
        try:
            manifest = build_local_manifest(
                run_id=ti.run_id,
                logical_date=logical_date.isoformat() if logical_date else "unknown",
                conf=conf,
                fixture_path=FIXTURE_PATH,
            )
        except ValueError as exc:
            # Malformed run input cannot be fixed by retrying the same run.
            raise AirflowFailException("manifest configuration failed local contract validation") from exc

        if conf.get("simulate_transient_once") is True and ti.try_number == 1:
            # Explicit local-only recovery demonstration. This has no side effect.
            raise AirflowException("local one-shot transient failure injection")
        manifest["resolver_try_number"] = ti.try_number
        manifest["recovery_status"] = (
            "RECOVERED_AFTER_BOUNDED_RETRY" if ti.try_number > 1 else "NO_RECOVERY_NEEDED"
        )
        return manifest

    @task(task_id="consume_silver")
    def consume_silver(manifest: dict) -> dict:
        try:
            return consume_local_silver(manifest, fixture_path=FIXTURE_PATH)
        except ValueError as exc:
            raise AirflowFailException("local Silver fixture failed its integrity contract") from exc

    @task(task_id="dbt_transform")
    def dbt_transform(manifest: dict, silver_snapshot: dict) -> dict:
        # This computes a tiny Python fixture result to exercise orchestration.
        # It does not invoke dbt or assert that a BigQuery model ran.
        try:
            return transform_local_silver(manifest, silver_snapshot)
        except ValueError as exc:
            raise AirflowFailException("local dbt-stage input failed its contract") from exc

    @task(task_id="validate_quality")
    def validate_quality(manifest: dict, transformed: dict) -> dict:
        try:
            return validate_local_transformation(manifest, transformed)
        except ValueError as exc:
            raise AirflowFailException("local quality gate could not validate the result") from exc

    @task(task_id="publication_fence")
    def publication_fence_task(manifest: dict, quality: dict) -> dict:
        # Even a passing fixture is never written or published by this DAG.
        return publication_fence(manifest, quality)

    @task(task_id="record_run_metadata")
    def record_run_metadata(
        manifest: dict,
        silver_snapshot: dict,
        transformed: dict,
        quality: dict,
        publication: dict,
    ) -> dict:
        receipt = {
            "run_id": manifest["run_id"],
            "batch_id": manifest["batch_id"],
            "source_status": manifest["source_status"],
            "silver_status": silver_snapshot["status"],
            "dbt_execution": transformed["dbt_execution"],
            "quality_status": quality["status"],
            "publication_status": publication["status"],
            "did_publish": publication["did_publish"],
            "previous_publication_unchanged": publication[
                "previous_publication_unchanged"
            ],
            "recovery_status": manifest["recovery_status"],
            "resolver_try_number": manifest["resolver_try_number"],
        }
        _LOGGER.info("DATAFORGE_AIRFLOW_LOCAL_RECEIPT %s", json.dumps(receipt, sort_keys=True))
        return receipt

    @task(task_id="recovery_alert_hook")
    def recovery_alert_hook(receipt: dict) -> dict:
        """Record the success/retry outcome locally; final failures use the DAG callback."""
        hook_receipt = {
            "hook": "LOCAL_LOG_ONLY",
            "run_id": receipt["run_id"],
            "recovery_status": receipt["recovery_status"],
            "resolver_try_number": receipt["resolver_try_number"],
            "alert_sent": False,
        }
        _LOGGER.info("DATAFORGE_AIRFLOW_RECOVERY_HOOK %s", json.dumps(hook_receipt, sort_keys=True))
        return {**receipt, "recovery_alert_hook": hook_receipt}

    manifest = resolve_manifest()
    silver_snapshot = consume_silver(manifest)
    transformed = dbt_transform(manifest, silver_snapshot)
    quality = validate_quality(manifest, transformed)
    publication = publication_fence_task(manifest, quality)
    receipt = record_run_metadata(manifest, silver_snapshot, transformed, quality, publication)
    recovery_alert_hook(receipt)


dataforge_week7_local_reference()
