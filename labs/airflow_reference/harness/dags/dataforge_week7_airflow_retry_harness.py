"""Trim the production Mini3 DAG to its real ingest task and its prerequisites."""

from __future__ import annotations

import os
from datetime import timedelta
from unittest.mock import patch

from airflow import sdk as airflow_sdk
from airflow.sdk import DeadlineAlert, DeadlineReference, SyncCallback
from airflow.sdk.definitions._internal.contextmanager import DagContext

_TESTED_DAG_ID = "dataforge_week7_weather_cloud"
_TEST_SCENARIO = os.environ["DATAFORGE_AIRFLOW_HARNESS_SCENARIO"]
_original_dag_decorator = airflow_sdk.dag


def _disable_schedule_for_test_dag(*args, **kwargs):
    if kwargs.get("dag_id") == _TESTED_DAG_ID and _TEST_SCENARIO != "backfill":
        kwargs["schedule"] = None
    return _original_dag_decorator(*args, **kwargs)


# Keep the production task graph and callables, but avoid a real-time scheduled DagRun in this harness.
airflow_sdk.dag = _disable_schedule_for_test_dag
try:
    import dataforge_week7_weather_cloud as production  # noqa: E402
finally:
    airflow_sdk.dag = _original_dag_decorator

from dataforge_week7_airflow_test_session import (  # noqa: E402
    make_authorized_session,
    make_fake_execution_receipt,
)

production._read_cloud_execution_receipt = make_fake_execution_receipt


def _dag_from_entry(entry):
    return entry[0] if isinstance(entry, tuple) else entry


_entries = [
    entry
    for entry in list(DagContext.autoregistered_dags)
    if _dag_from_entry(entry).dag_id == production.DAG_ID
]
if len(_entries) > 1:
    raise RuntimeError("production Mini3 DAG factory auto-registered more than once")

_production_dag = (
    _dag_from_entry(_entries[0])
    if _entries
    else production.dataforge_week7_weather_cloud()
)
if _TEST_SCENARIO == "deadline":
    _production_dag.deadline = [
        DeadlineAlert(
            reference=DeadlineReference.DAGRUN_QUEUED_AT,
            interval=timedelta(seconds=2),
            callback=SyncCallback(production.local_deadline_log),
        )
    ]
for _entry in _entries:
    DagContext.autoregistered_dags.discard(_entry)

_sensor_task_ids = {"wait_for_api_ingest"}
_target_task_ids = {"wait_for_api_ingest"}
if _TEST_SCENARIO == "backfill":
    _sensor_task_ids.add("wait_for_bigquery_landing")
    _target_task_ids = {"wait_for_bigquery_landing"}

dag = _production_dag.partial_subset(
    task_ids=_target_task_ids,
    include_upstream=True,
    include_downstream=False,
)
for _entry in list(DagContext.autoregistered_dags):
    if _dag_from_entry(_entry).dag_id == production.DAG_ID:
        DagContext.autoregistered_dags.discard(_entry)
del _production_dag, _entries

# The scheduler and task process must reload this harness file, not the production DAG file.
dag.fileloc = __file__
_expected_task_ids = {
    "resolve_cloud_request",
    "authorize_cloud_execution",
    "verify_gcp_schedule_paused",
    "execute_api_ingest",
}
if _TEST_SCENARIO == "backfill":
    _expected_task_ids.update(
        {
            "wait_for_api_ingest",
            "read_execution_receipt",
            "load_bigquery_landing",
            "wait_for_bigquery_landing",
        }
    )
else:
    _expected_task_ids.add("wait_for_api_ingest")
if set(dag.task_ids) != _expected_task_ids:
    raise RuntimeError(f"unexpected production Mini3 subset: {sorted(dag.task_ids)}")


def _run_with_fake_session(callable_, *args, **kwargs):
    with patch.object(production, "_authorized_session", new=make_authorized_session):
        return callable_(*args, **kwargs)


_preflight = dag.get_task("verify_gcp_schedule_paused")
_production_preflight_callable = _preflight.python_callable


def _verify_scheduler_with_fake_session():
    return _run_with_fake_session(_production_preflight_callable)


_preflight.python_callable = _verify_scheduler_with_fake_session

_ingest = dag.get_task("execute_api_ingest")
_production_ingest_callable = _ingest.python_callable


def _execute_ingest_with_fake_session(request):
    return _run_with_fake_session(_production_ingest_callable, request)


_ingest.python_callable = _execute_ingest_with_fake_session
# Keep the production retry count; shorten only the CI wait before Airflow's next attempt.
_ingest.retry_delay = timedelta(seconds=1)
_ingest.retry_exponential_backoff = False

if _TEST_SCENARIO == "backfill":
    _landing = dag.get_task("load_bigquery_landing")
    _production_landing_callable = _landing.python_callable

    def _load_landing_with_fake_session(receipt):
        return _run_with_fake_session(_production_landing_callable, receipt)

    _landing.python_callable = _load_landing_with_fake_session

for _sensor_task_id in _sensor_task_ids:
    dag.get_task(_sensor_task_id).poke_interval = 1
_production_sensor_poke = production.CloudRunExecutionReceiptSensor.poke


def _poke_with_fake_session(sensor, context):
    with patch.object(production, "_authorized_session", new=make_authorized_session):
        return _production_sensor_poke(sensor, context)


production.CloudRunExecutionReceiptSensor.poke = _poke_with_fake_session
