"""Static safety checks for the Week 9 DataOps dispatch and cleanup workflows."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def load_workflow(path: str) -> dict:
    return yaml.load(
        (ROOT / path).read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def step_index(steps: list[dict], name: str) -> int:
    return next(index for index, step in enumerate(steps) if step.get("name") == name)


def test_manual_cloud_build_is_bound_to_exact_open_same_repo_pr_head() -> None:
    workflow = load_workflow(".github/workflows/week9-dataops.yml")
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert {"pr_number", "run_cloud_build", "run_fault_matrix"} <= set(inputs)

    job = workflow["jobs"]["cloud-pr"]
    assert "inputs.run_cloud_build" in job["if"]
    assert job["env"]["PR_DATASET"] == "dbt_ci_pr_${{ github.event.pull_request.number || inputs.pr_number }}"
    assert "inputs.pr_number" in job["env"]["PR_DATASET"]

    smoke_steps = workflow["jobs"]["wif-smoke"]["steps"]
    validation = smoke_steps[step_index(smoke_steps, "Validate the exact PR ref for a manual cloud build")]
    script = validation["run"]
    assert "inputs.run_cloud_build" in validation["if"]
    assert "^[1-9][0-9]*$" in script
    assert ".head.repo.id" in script and ".head.sha" in script
    assert '!= "$CURRENT_SHA"' in script
    assert step_index(smoke_steps, validation["name"]) < step_index(
        smoke_steps, "Authenticate with the allowlisted WIF provider"
    )


def test_manual_cloud_build_comments_with_its_sanitized_run_artifact() -> None:
    workflow = load_workflow(".github/workflows/week9-dataops.yml")
    cloud = workflow["jobs"]["cloud-pr"]
    upload = next(step for step in cloud["steps"] if step.get("name") == "Upload sanitized PR build summary")
    assert "inputs.pr_number" in upload["with"]["name"]

    comment = workflow["jobs"]["pr-comment"]
    assert "github.event_name == 'workflow_dispatch'" in comment["if"]
    assert "inputs.run_cloud_build" in comment["if"]
    assert comment["env"]["PR_NUMBER"] == "${{ github.event.pull_request.number || inputs.pr_number }}"
    steps = comment["steps"]
    validation = steps[step_index(steps, "Revalidate the manual PR before commenting")]
    assert "inputs.run_cloud_build" in validation["if"]
    assert "^[1-9][0-9]*$" in validation["run"]
    assert ".head.repo.id" in validation["run"] and ".head.sha" in validation["run"]
    assert step_index(steps, validation["name"]) < step_index(
        steps, "Download the run summary or prepare an unavailable status"
    )
    download_script = steps[step_index(steps, "Download the run summary or prepare an unavailable status")]["run"]
    assert 'artifact="week9-dataops-summary-${PR_NUMBER}-${GITHUB_RUN_ID}"' in download_script
    create_comment = steps[step_index(steps, "Create or update the DataOps comment")]["run"]
    assert '"repos/$GITHUB_REPOSITORY/issues/$PR_NUMBER/comments"' in create_comment


def test_live_fault_matrix_is_fixed_to_w9_drill() -> None:
    workflow = load_workflow(".github/workflows/week9-dataops.yml")
    live = workflow["jobs"]["fault-matrix-live"]
    assert live["env"]["FAULT_DATASET"] == "w9_drill"
    assert "inputs.run_fault_matrix" in live["if"]
    inject = next(step for step in live["steps"] if step.get("name") == "Run F07/F10 only in the isolated W9 drill dataset")
    assert "--dataset w9_drill" in inject["run"]
    assert "${{ inputs." not in inject["run"]

    helper = (ROOT / "deploy/dataops_toolbox/week9_live_faults.py").read_text(encoding="utf-8")
    assert 'args.dataset != "w9_drill"' in helper
    assert 'dataset != "w9_drill"' in helper
    assert "weather_7date_slice.parquet" in helper
    assert "CI (isolated BigQuery w9_drill test ran" in helper
    assert "CI (isolated BigQuery w9_drill test did not complete" in helper
    assert "`dataforge-p7-lab-d0f725.weather_mini3." not in helper
    assert "dbt_weather_mini3" not in helper


def test_manual_cleanup_requires_explicit_flag_and_merged_same_repo_pr() -> None:
    workflow = load_workflow(".github/workflows/week9-cleanup.yml")
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["run_cleanup"]["type"] == "boolean"
    assert "pr_number" in inputs

    job = workflow["jobs"]["manual-pr-cleanup"]
    assert "inputs.run_cleanup" in job["if"]
    assert job["env"]["PR_DATASET"] == "dbt_ci_pr_${{ inputs.pr_number }}"
    steps = job["steps"]
    validation = steps[step_index(steps, "Validate the exact same-repository merged PR number")]
    script = validation["run"]
    assert "^[1-9][0-9]*$" in script
    assert ".merged_at" in script and ".head.repo.id" in script
    assert '!= "$BASE_REPO_ID"' in script
    assert step_index(steps, validation["name"]) < step_index(
        steps, "Authenticate with the allowlisted cleanup workflow"
    )


def test_stale_sweep_requires_closed_pr_and_old_dataset_creation_time() -> None:
    workflow = load_workflow(".github/workflows/week9-cleanup.yml")
    job = workflow["jobs"]["stale-dataset-sweep"]
    pr_query = next(step["run"] for step in job["steps"] if step.get("name") == "Find stale PR dataset candidates through GitHub PR metadata")
    delete_script = next(step["run"] for step in job["steps"] if step.get("name") == "Check dataset creation age and delete stale isolated datasets")
    assert "pulls?state=closed" in pr_query
    assert ".updated_at" in pr_query
    assert "timedelta(days=2)" in pr_query
    assert ".creationTime" in delete_script
    assert "now_ms - created_ms >= stale_after_ms" in delete_script
