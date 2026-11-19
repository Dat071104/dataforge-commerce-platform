"""Static safety checks for the Week 9 DataOps dispatch and cleanup workflows."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def load_workflow(path: str) -> dict:
    return yaml.load(
        (ROOT / path).read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def load_lineage_helper():
    helper_path = ROOT / "deploy/dataops_toolbox/week9_lineage_build.py"
    spec = importlib.util.spec_from_file_location("week9_lineage_build", helper_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_cloud_copy_uses_validated_partition_literals_and_pr_only_destination() -> None:
    workflow = load_workflow(".github/workflows/week9-dataops.yml")
    cloud_steps = workflow["jobs"]["cloud-pr"]["steps"]
    copy_step = next(
        step for step in cloud_steps if step.get("name") == "Copy the latest seven weather dates into the PR dataset"
    )
    script = copy_step["run"]
    assert "INFORMATION_SCHEMA.PARTITIONS" in script
    assert "table_name = 'weather_landing'" in script
    assert "ORDER BY partition_id DESC" in script and "LIMIT 7" in script
    assert "len(partition_rows) != 7" in script
    assert 're.fullmatch(r"[0-9]{8}", value)' in script
    assert 'datetime.strptime(value, "%Y%m%d")' in script
    assert 'print(", ".join(f"DATE \'{value}\'" for value in dates))' in script
    assert "WHERE observation_date IN ($partition_filter)" in script
    assert "SELECT DISTINCT observation_date" not in script
    assert "FROM \\`${PROJECT_ID}.weather_mini3.weather_landing\\`" in script
    assert "CREATE OR REPLACE TABLE \\`${PROJECT_ID}.${PR_DATASET}.weather_landing\\`" in script
    assert script.count("--maximum_bytes_billed=1073741824") >= 2
    assert '> "$RUNNER_TEMP/weather-partitions.csv"' in script
    assert 'echo "$partition_filter"' not in script and 'echo "$partition_ids"' not in script


def test_manual_lineage_build_is_exact_head_gated_and_fixed_to_w9_drill() -> None:
    workflow_path = ROOT / ".github/workflows/week9-dataops.yml"
    workflow = load_workflow(".github/workflows/week9-dataops.yml")
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["run_lineage_build"]["type"] == "boolean"
    assert inputs["run_lineage_build"]["default"] == "false"
    parsed_inputs = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))[True]["workflow_dispatch"]["inputs"]
    assert parsed_inputs["run_lineage_build"]["default"] is False
    assert workflow["concurrency"]["cancel-in-progress"] == "false"

    guard = workflow["jobs"]["drill-dispatch-guard"]
    guard_step = guard["steps"][0]
    assert guard_step["env"]["RUN_LINEAGE_BUILD"] == "${{ inputs.run_lineage_build }}"
    assert guard_step["env"]["RUN_FAULT_MATRIX"] == "${{ inputs.run_fault_matrix }}"
    assert "select one per dispatch" in guard_step["run"]

    job = workflow["jobs"]["lineage-build"]
    assert job["if"] == "github.event_name == 'workflow_dispatch' && inputs.run_lineage_build"
    assert job["needs"] == ["drill-dispatch-guard"]
    assert job["env"]["DATASET"] == "w9_drill"
    assert job["concurrency"]["group"] == "week9-w9-drill-${{ github.repository }}"
    assert job["concurrency"]["cancel-in-progress"] == "false"
    assert "inputs.run_lineage_build" not in workflow["jobs"]["wif-smoke"]["if"]

    fault_job = workflow["jobs"]["fault-matrix-live"]
    assert "drill-dispatch-guard" in fault_job["needs"]
    assert fault_job["concurrency"] == job["concurrency"]

    steps = job["steps"]
    validation = next(
        step for step in steps if step.get("name") == "Validate the exact open same-repository PR head before WIF"
    )
    validation_script = validation["run"]
    assert "^[1-9][0-9]*$" in validation_script
    assert ".head.repo.id" in validation_script and ".head.sha" in validation_script
    assert '"$pr_state" != "open"' in validation_script
    assert '!= "$CURRENT_SHA"' in validation_script
    assert step_index(steps, validation["name"]) < step_index(steps, "Check out the validated dispatched PR head")
    assert step_index(steps, validation["name"]) < step_index(steps, "Authenticate the CI service account with WIF")

    access_check = next(
        step for step in steps if step.get("name") == "Confirm WIF access to the fixed W9 drill dataset"
    )
    assert 'bq ls "$PROJECT_ID:$DATASET" >/dev/null 2>&1' in access_check["run"]

    helper_step = next(step for step in steps if step.get("name") == "Run bounded copy, destination guard, and dbt build")
    assert "week9_lineage_build.py" in helper_step["run"]
    assert '"$GOOGLE_APPLICATION_CREDENTIALS:/tmp/gha-creds.json:ro"' in helper_step["run"]
    assert "--env ACTIONS_ID_TOKEN_REQUEST_URL" in helper_step["run"]
    upload = next(step for step in steps if step.get("name") == "Upload sanitized lineage and query-usage summary")
    assert upload["if"] == "always()"
    assert "w9-lineage-summary.json" in upload["with"]["path"]

    helper = (ROOT / "deploy/dataops_toolbox/week9_lineage_build.py").read_text(encoding="utf-8")
    assert 'PROJECT_ID = "dataforge-p7-lab-d0f725"' in helper
    assert 'SOURCE_DATASET = "weather_mini3"' in helper
    assert 'TARGET_DATASET = "w9_drill"' in helper
    assert "MAXIMUM_BYTES_BILLED = 1024**3" in helper
    assert "INFORMATION_SCHEMA.PARTITIONS" in helper
    assert "REGEXP_CONTAINS(partition_id" in helper
    assert "DATE '{value.isoformat()}'" in helper
    assert "CREATE OR REPLACE TABLE" in helper
    assert '"landed_at": ("TIMESTAMP", "REQUIRED")' in helper
    assert "schema_signature(copied_table.schema, include_mode=False) != EXPECTED_OUTPUT_TYPES" in helper
    assert "validate_manifest(manifest)" in helper
    assert "node.get(\"schema\") != TARGET_DATASET" in helper
    assert "source.get(\"schema\") != TARGET_DATASET" in helper
    assert '"DATAFORGE_DQ_RESULTS_ENABLED": "false"' in helper
    assert "packages.yml" in helper
    assert "summarize_dbt_results" in helper
    assert '"dbt_jobs_seen"' in helper and '"adapter_bytes_billed"' in helper
    assert '"bigquery_queries"' in helper and '"billing_sku": "UNVERIFIED"' in helper
    assert 'capture_output=True' in helper and "output suppressed" in helper
    assert "dbt_weather_mini3" not in helper and "w9_drill_silver" not in helper
    assert '"--no-introspect"' in helper
    assert helper.index("packages.yml") < helper.index("client.query(")
    assert not (ROOT / "dbt/dataforge/packages.yml").exists()
    requirements_lock = (ROOT / "deploy/dataops_toolbox/requirements.lock").read_text(encoding="utf-8")
    assert "dbt-bigquery==1.11.3" in requirements_lock

    profile = load_workflow("dbt/dataforge/profiles.example.yml")
    assert profile["dataforge"]["outputs"]["w9_ci"]["maximum_bytes_billed"] == "1073741824"


def test_lineage_helper_renders_only_seven_real_partition_date_literals() -> None:
    helper = load_lineage_helper()
    partition_ids = [f"202611{day:02d}" for day in range(19, 12, -1)]
    filter_sql, as_of_date = helper.partition_literals(partition_ids)
    assert filter_sql == ", ".join(f"DATE '2026-11-{day:02d}'" for day in range(19, 12, -1))
    assert as_of_date.isoformat() == "2026-11-19"

    for invalid in (partition_ids[:-1], [*partition_ids[:-1], partition_ids[0]], ["20261340", *partition_ids[1:]]):
        try:
            helper.partition_literals(invalid)
        except helper.LineageBuildError:
            pass
        else:
            raise AssertionError("Invalid partition metadata should fail closed")


def test_dbt_cost_summary_deduplicates_repeated_job_ids() -> None:
    helper = load_lineage_helper()
    summary = helper.summarize_dbt_results(
        [
            {"adapter_response": {"job_id": "job_a", "bytes_billed": 100}},
            {"adapter_response": {"job_id": "job_a", "bytes_billed": 100}},
            {"adapter_response": {"job_id": "job_b", "bytes_billed": "250"}},
            {"adapter_response": {"job_id": None, "bytes_billed": 50}},
        ]
    )
    assert summary["dbt_jobs_seen"] == 2
    assert summary["dbt_jobs_with_billing"] == 2
    assert summary["adapter_bytes_billed"] == 400
    assert summary["dbt_results_with_billing_without_job_id"] == 1


def test_lineage_manifest_guard_rejects_any_weather_relation_outside_w9_drill() -> None:
    helper = load_lineage_helper()
    manifest = {
        "nodes": {
            "model.dataforge.int_weather_daily": {
                "resource_type": "model",
                "tags": ["weather_mini3", "silver"],
                "database": "dataforge-p7-lab-d0f725",
                "schema": "w9_drill",
            }
        },
        "sources": {
            "source.dataforge.weather_mini3.weather_landing": {
                "source_name": "weather_mini3",
                "name": "weather_landing",
                "database": "dataforge-p7-lab-d0f725",
                "schema": "w9_drill",
            }
        },
    }
    assert helper.validate_manifest(manifest) == 1
    manifest["nodes"]["model.dataforge.int_weather_daily"]["schema"] = "w9_drill_silver"
    try:
        helper.validate_manifest(manifest)
    except helper.LineageBuildError:
        pass
    else:
        raise AssertionError("A non-w9_drill model destination should fail closed")


def test_silver_denial_probe_captures_both_streams_and_rejects_404() -> None:
    workflow = load_workflow(".github/workflows/week9-dataops.yml")
    smoke_steps = workflow["jobs"]["wif-smoke"]["steps"]
    probe = next(step for step in smoke_steps if step.get("name") == "Verify silver dataset read is denied")
    script = probe["run"]
    assert 'bq ls silver >"$probe_file" 2>&1' in script
    assert "(^|[^0-9])404([^0-9]|$)|not found|notfound" in script
    assert "(^|[^0-9])403([^0-9]|$)|access denied|permission[[:space:]_-]+denied" in script
    assert "UNVERIFIED" in script
    assert "bigquery.datasets.get" not in script
    assert 'cat "$probe_file"' not in script


def test_manual_offline_checks_use_the_dispatched_sha_without_cloud_permissions() -> None:
    workflow = load_workflow(".github/workflows/week9-dataops.yml")
    input_spec = workflow["on"]["workflow_dispatch"]["inputs"]["run_offline_checks"]
    assert input_spec["type"] == "boolean"
    assert input_spec["default"] == "false"

    for name in ("lint", "toolbox"):
        job = workflow["jobs"][name]
        assert "github.event_name == 'pull_request'" in job["if"]
        assert "github.event_name == 'workflow_dispatch'" in job["if"]
        assert "inputs.run_offline_checks" in job["if"]
        assert job["permissions"] == {"contents": "read"}
        checkout = next(step for step in job["steps"] if step.get("name") == "Check out repository")
        assert checkout["with"]["ref"] == "${{ github.sha }}"


def test_runner_temp_context_is_not_used_in_job_env_or_run_scripts() -> None:
    paths = (
        ".github/workflows/week9-dataops.yml",
        ".github/workflows/week9-cleanup.yml",
        ".github/workflows/week9-cd.yml",
        ".github/workflows/week9-wif-deny.yml",
    )
    for path in paths:
        workflow = load_workflow(path)
        for job_name, job in workflow["jobs"].items():
            assert all("${{ runner.temp }}" not in str(value) for value in job.get("env", {}).values()), path
            for step in job.get("steps", []):
                assert "${{ runner.temp }}" not in step.get("run", ""), (
                    f"{path} job {job_name} step {step.get('name', '<unnamed>')}"
                )

    dataops = load_workflow(".github/workflows/week9-dataops.yml")
    cloud_setup = next(
        step
        for step in dataops["jobs"]["cloud-pr"]["steps"]
        if step.get("name") == "Prepare non-secret profile and dbt temp paths"
    )
    assert 'DBT_TARGET_PATH=$RUNNER_TEMP/dbt-target" >> "$GITHUB_ENV"' in cloud_setup["run"]
    assert 'DBT_LOG_PATH=$RUNNER_TEMP/dbt-logs" >> "$GITHUB_ENV"' in cloud_setup["run"]

    cd_workflow = load_workflow(".github/workflows/week9-cd.yml")
    cd_setup = next(
        step
        for step in cd_workflow["jobs"]["publish-main-artifacts"]["steps"]
        if step.get("name") == "Set dbt temporary paths"
    )
    assert 'DBT_TARGET_PATH=$RUNNER_TEMP/dbt-target" >> "$GITHUB_ENV"' in cd_setup["run"]
    assert 'DBT_LOG_PATH=$RUNNER_TEMP/dbt-logs" >> "$GITHUB_ENV"' in cd_setup["run"]


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


def test_automatic_trusted_pr_jobs_are_paused_until_provider_switch_is_enabled() -> None:
    dataops = load_workflow(".github/workflows/week9-dataops.yml")
    guarded_jobs = ("wif-smoke", "cloud-pr", "fault-matrix-live", "pr-comment")
    for name in guarded_jobs:
        condition = dataops["jobs"][name]["if"]
        assert "vars.W9_WIF_PR_TARGET_ENABLED == 'true'" in condition
        assert "github.event_name == 'workflow_dispatch'" in condition
        dispatch_clause = condition[condition.index("github.event_name == 'workflow_dispatch'"):]
        assert "vars.W9_WIF_PR_TARGET_ENABLED" not in dispatch_clause

    cloud_pause = dataops["jobs"]["same-repository-cloud-paused"]
    assert "vars.W9_WIF_PR_TARGET_ENABLED != 'true'" in cloud_pause["if"]
    assert "head.repo.id == github.repository_id" in cloud_pause["if"]
    assert "W9_WIF_PR_TARGET_ENABLED=true" in cloud_pause["steps"][0]["run"]

    cleanup = load_workflow(".github/workflows/week9-cleanup.yml")
    close_job = cleanup["jobs"]["closed-pr-cleanup"]
    assert "vars.W9_WIF_PR_TARGET_ENABLED == 'true'" in close_job["if"]
    assert "workflow_dispatch" not in close_job["if"]
    cleanup_pause = cleanup["jobs"]["same-repository-cleanup-paused"]
    assert "vars.W9_WIF_PR_TARGET_ENABLED != 'true'" in cleanup_pause["if"]
    assert "head.repo.id == github.repository_id" in cleanup_pause["if"]
    assert "W9_WIF_PR_TARGET_ENABLED=true" in cleanup_pause["steps"][0]["run"]
    assert "vars.W9_WIF_PR_TARGET_ENABLED" not in cleanup["jobs"]["manual-pr-cleanup"]["if"]


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
