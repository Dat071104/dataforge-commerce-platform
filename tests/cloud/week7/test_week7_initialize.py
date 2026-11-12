from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.week7_initialize_cloud import (
    BOOTSTRAP_SQL,
    CURRENTNESS_VIEW_SQL,
    EXPECTED_PROJECT,
    EXPECTED_PROJECT_NUMBER,
    EXPECTED_REGION,
    Week7BootstrapError,
    _load_approved_sql,
    _load_approved_target,
    _load_currentness_view_sql,
    initialize_week7,
)


def test_bootstrap_target_is_locked_to_the_approved_project(tmp_path: Path):
    target_path = tmp_path / "target.json"
    target_path.write_text(
        json.dumps(
            {
                "project_id": EXPECTED_PROJECT,
                "project_number": EXPECTED_PROJECT_NUMBER,
                "region": EXPECTED_REGION,
            }
        ),
        encoding="utf-8",
    )
    assert _load_approved_target(target_path)["project_id"] == EXPECTED_PROJECT

    target_path.write_text(
        json.dumps(
            {
                "project_id": "unrelated-project",
                "project_number": EXPECTED_PROJECT_NUMBER,
                "region": EXPECTED_REGION,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(Week7BootstrapError, match="approved project and region"):
        _load_approved_target(target_path)


def test_bootstrap_sql_matches_only_the_week7_singleton_tables():
    target = {
        "project_id": EXPECTED_PROJECT,
        "project_number": EXPECTED_PROJECT_NUMBER,
        "region": EXPECTED_REGION,
    }
    sql = _load_approved_sql(target, BOOTSTRAP_SQL)
    assert "ops.week7_publish_lock" in sql
    assert "gold_week7.week7_publication_pointer" in sql
    assert "publication_is_current = FALSE" in sql
    assert "BEGIN TRANSACTION" in sql


def test_bootstrap_refuses_other_projects_and_destructive_sql(tmp_path: Path):
    target = {
        "project_id": EXPECTED_PROJECT,
        "project_number": EXPECTED_PROJECT_NUMBER,
        "region": EXPECTED_REGION,
    }
    wrong_project_sql = tmp_path / "wrong-project.sql"
    wrong_project_sql.write_text(
        "SELECT * FROM `another-project.ops.week7_publish_lock`;", encoding="utf-8"
    )
    with pytest.raises(Week7BootstrapError, match="does not match"):
        _load_approved_sql(target, wrong_project_sql)

    destructive_sql = tmp_path / "drop.sql"
    destructive_sql.write_text(
        "SELECT * FROM `dataforge-p7-lab-d0f725.ops.week7_publish_lock`;\n"
        "SELECT * FROM `dataforge-p7-lab-d0f725.gold_week7.week7_publication_pointer`;\n"
        "DROP TABLE `dataforge-p7-lab-d0f725.ops.week7_publish_lock`;",
        encoding="utf-8",
    )
    with pytest.raises(Week7BootstrapError, match="destructive"):
        _load_approved_sql(target, destructive_sql)


def test_bootstrap_defaults_to_dry_run(capsys):
    receipt = initialize_week7(execute=False)
    captured = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "DRY_RUN_NO_CLOUD_WRITE"
    assert captured["project_id"] == EXPECTED_PROJECT
    assert receipt["bootstrap_job_id"] is None


def test_currentness_view_replacement_is_limited_to_the_approved_filtered_view(tmp_path: Path):
    target = {
        "project_id": EXPECTED_PROJECT,
        "project_number": EXPECTED_PROJECT_NUMBER,
        "region": EXPECTED_REGION,
    }
    sql = _load_currentness_view_sql(target, CURRENTNESS_VIEW_SQL)
    assert "pointer.publication_is_current IS TRUE" in sql

    wrong_view = tmp_path / "wrong-view.sql"
    wrong_view.write_text(
        "CREATE OR REPLACE VIEW `dataforge-p7-lab-d0f725.gold_week7.other_view` AS "
        "SELECT * FROM `dataforge-p7-lab-d0f725.gold_week7.week7_order_reconciliation_versions`;",
        encoding="utf-8",
    )
    with pytest.raises(Week7BootstrapError, match="filtered view"):
        _load_currentness_view_sql(target, wrong_view)
