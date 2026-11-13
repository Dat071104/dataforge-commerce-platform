from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / "cloud" / "workflows" / "week7_weather_workflow.yaml"
TERRAFORM = REPO_ROOT / "cloud" / "terraform" / "dev" / "week7_weather.tf"
VARIABLES = REPO_ROOT / "cloud" / "terraform" / "dev" / "week7_weather_variables.tf"


def test_controlled_alert_failure_is_manual_and_happens_before_publication() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'test_fail_before_publish: ${default(map.get(args, "test_fail_before_publish"), false)}' in workflow
    assert '${test_fail_before_publish and trigger != "manual"}' in workflow
    assert '${test_fail_before_publish and no_new_batch}' in workflow
    assert workflow.index("invoke_dbt_weather_build_and_tests") < workflow.index(
        "branch_controlled_failure_test"
    )
    assert "invoke_explicit_dbt_tests" not in workflow
    assert workflow.index("branch_controlled_failure_test") < workflow.index(
        "invoke_guarded_weather_publication"
    )
    assert "DATAFORGE_WEATHER_CONTROLLED_ALERT_TEST" in workflow


def test_live_email_channel_and_policy_are_opt_in_and_test_only() -> None:
    terraform = TERRAFORM.read_text(encoding="utf-8")
    variables = VARIABLES.read_text(encoding="utf-8")

    assert 'variable "week7_weather_notification_channel_enabled"' in variables
    assert "default     = false" in variables
    assert "sensitive   = true" in variables
    assert 'resource "google_monitoring_notification_channel" "week7_weather_email_test"' in terraform
    assert 'resource "google_monitoring_alert_policy" "week7_weather_failure"' in terraform
    assert 'jsonPayload.event="DATAFORGE_WEATHER_CONTROLLED_ALERT_TEST"' in terraform
    assert 'notification_prompts = ["OPENED"]' in terraform
    assert 'period = "3600s"' in terraform
