"""Trim the production Mini3 DAG to its real ingest task and its prerequisites."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from airflow.sdk.definitions.dag import DagContext

import dataforge_week7_weather_cloud as production
from dataforge_week7_airflow_test_session import make_authorized_session


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
for _entry in _entries:
    DagContext.autoregistered_dags.discard(_entry)

dag = _production_dag.partial_subset(
    task_ids={"execute_api_ingest"},
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
