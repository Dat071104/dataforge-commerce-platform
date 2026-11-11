from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from scripts.week7_capture_state import Week7StateError, _read_target
from scripts.week7_run_workflow import (
    RunOptions,
    WorkflowClientError,
    build_workflow_arguments,
    run_workflow,
)

TARGET = {
    "project_id": "dataforge-p7-lab-d0f725",
    "project_number": "955038620072",
    "region": "us-central1",
    "bucket": "dataforge-p7-lab-d0f725-bronze",
}
_BATCH_ID = "a" * 64
_MANIFEST_URI = (
    "gs://dataforge-p7-lab-d0f725-bronze/manifests/week5/"
    f"batch_id={_BATCH_ID}/manifest.json"
)
_WORKFLOW_SOURCE = Path(__file__).resolve().parents[3] / "cloud" / "workflows" / "week7_workflow.yaml"
_PUBLICATION_MACROS = Path(__file__).resolve().parents[3] / "dbt" / "dataforge" / "macros" / "week7_publication.sql"


def _options(**kwargs: Any) -> RunOptions:
    base = RunOptions(
        no_new_batch=False,
        manifest_uri=_MANIFEST_URI,
        manifest_generation=123,
        batch_id=_BATCH_ID,
        run_mode="normal",
        test_fail_after_merge_once=False,
        test_fail_dbt_build=False,
        test_fail_before_publish=False,
        test_hold_after_lock_seconds=0,
        timeout_seconds=2400,
        poll_interval_seconds=5,
    )
    return replace(base, **kwargs)


def test_no_new_batch_is_an_explicit_safe_input():
    assert build_workflow_arguments(_options(no_new_batch=True, manifest_uri=None, manifest_generation=None, batch_id=None), TARGET) == {
        "no_new_batch": True,
        "trigger": "manual",
    }


@pytest.mark.parametrize(
    "options",
    [
        _options(manifest_generation=None),
        _options(batch_id="not-a-sha"),
        _options(manifest_uri="gs://another-bucket/manifests/manifest.json"),
        _options(no_new_batch=True),
        _options(test_fail_after_merge_once=True, test_fail_dbt_build=True),
        _options(test_fail_dbt_build=True, test_fail_before_publish=True),
        _options(test_hold_after_lock_seconds=31),
        _options(timeout_seconds=3601),
    ],
)
def test_invalid_inputs_fail_before_any_workflow_api_request(options):
    with pytest.raises(WorkflowClientError):
        build_workflow_arguments(options, TARGET)


class _Credentials:
    token = "must-never-be-printed"

    def refresh(self, _: Any) -> None:
        pass


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


class _RequestSession:
    def __init__(self):
        self.posts: list[dict[str, Any]] = []
        self.gets = 0

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int):
        self.posts.append({"url": url, "json": json, "timeout": timeout})
        return _Response(
            {"name": "projects/dataforge-p7-lab-d0f725/locations/us-central1/"
                    "workflows/dataforge-week7-orchestrator/executions/test-execution"}
        )

    def get(self, url: str, *, headers: dict[str, str], timeout: int):
        self.gets += 1
        return _Response(
            {
                "state": "SUCCEEDED",
                "name": url.split("/v1/", 1)[1],
                "result": json.dumps({"status": "NO_NEW_BATCH"}),
                "startTime": "2026-11-11T00:00:00Z",
                "endTime": "2026-11-11T00:00:01Z",
            }
        )


def test_workflow_execution_uses_adc_and_returns_a_sanitized_terminal_receipt():
    session = _RequestSession()
    options = _options(no_new_batch=True, manifest_uri=None, manifest_generation=None, batch_id=None)
    result = run_workflow(
        options=options,
        target=TARGET,
        request_session=session,
        credential_factory=lambda **_: (_Credentials(), TARGET["project_id"]),
        sleep=lambda _: None,
        monotonic=lambda: 100.0,
    )

    assert result["state"] == "SUCCEEDED"
    assert result["result"] == {"status": "NO_NEW_BATCH"}
    assert result["workflow_execution_name"].endswith("/test-execution")
    assert session.gets == 1
    assert "must-never-be-printed" not in json.dumps(result)


def test_adc_project_mismatch_stops_before_api_call():
    session = _RequestSession()
    options = _options(no_new_batch=True, manifest_uri=None, manifest_generation=None, batch_id=None)
    with pytest.raises(WorkflowClientError, match="ADC project"):
        run_workflow(
            options=options,
            target=TARGET,
            request_session=session,
            credential_factory=lambda **_: (_Credentials(), "unrelated-project"),
            sleep=lambda _: None,
            monotonic=lambda: 100.0,
        )
    assert not session.posts


def test_storage_media_connector_json_result_is_a_manifest_map():
    workflow = _WORKFLOW_SOURCE.read_text(encoding="utf-8")
    assert "manifest: ${manifest_response}" in workflow
    assert "manifest_response.body" not in workflow
    assert "text.decode(manifest_response)" not in workflow
    assert "log_acquisition_status" in workflow
    assert 'condition: ${acquisition_status == "ACQUIRED"}' in workflow
    assert 'publication_is_current == "true"' in workflow


def test_current_gold_is_hidden_until_the_publication_transaction_sets_currentness():
    macro = _PUBLICATION_MACROS.read_text(encoding="utf-8")
    assert "SET publication_is_current = FALSE" in macro
    assert "SET publication_is_current = TRUE" in macro
    assert "WHERE pointer.publication_is_current IS TRUE" in macro


def test_state_capture_rejects_an_unapproved_project(tmp_path):
    target = tmp_path / "target.json"
    target.write_text(json.dumps({**TARGET, "project_id": "unrelated-project"}), encoding="utf-8")
    with pytest.raises(Week7StateError, match="approved isolated project"):
        _read_target(target)
