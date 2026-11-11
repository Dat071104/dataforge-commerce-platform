"""Network-free verification for event-log benchmark recovery."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from labs.spark_nyc_taxi.eventlog_report import recover_benchmark_report


def _job_start(job_id: int, stage_id: int, group_id: str, start_ms: int) -> dict:
    started = datetime.fromtimestamp(start_ms / 1000, timezone.utc)
    return {
        "Event": "SparkListenerJobStart",
        "Job ID": job_id,
        "Submission Time": started.strftime("%Y-%m-%dT%H:%M:%S.000GMT"),
        "Stage Infos": [{"Stage ID": stage_id}],
        "Properties": {"spark.jobGroup.id": group_id},
    }


def _task_end(stage_id: int) -> dict:
    return {
        "Event": "SparkListenerTaskEnd",
        "Stage ID": stage_id,
        "Task End Reason": {"Reason": "Success"},
        "Task Info": {"Duration": 500},
        "Task Metrics": {
            "Executor Run Time": 400,
            "Executor CPU Time": 1_000,
            "JVM GC Time": 0,
            "Memory Bytes Spilled": 0,
            "Disk Bytes Spilled": 0,
            "Input Metrics": {"Bytes Read": 100, "Records Read": 10},
            "Shuffle Read Metrics": {
                "Remote Bytes Read": 10,
                "Local Bytes Read": 20,
                "Total Records Read": 3,
            },
            "Shuffle Write Metrics": {"Shuffle Bytes Written": 30, "Shuffle Records Written": 4},
            "Output Metrics": {"Bytes Written": 5, "Records Written": 1},
        },
    }


def test_eventlog_recovery_emits_run_receipts_and_real_plans(tmp_path: Path):
    events = [{"Event": "SparkListenerApplicationStart", "App ID": "local-fixture"}]
    start_ms = 1_794_240_000_000
    job_id = 0
    stage_id = 0
    for variant in ("baseline", "broadcast_candidate"):
        for kind, indices in (("warmup", [0]), ("run", range(5))):
            for index in indices:
                group = f"week6-{variant}-{kind}-{index}-{job_id:010x}"
                current_start = start_ms + job_id * 2_000
                events.append(_job_start(job_id, stage_id, group, current_start))
                events.append(_task_end(stage_id))
                events.append(
                    {
                        "Event": "SparkListenerJobEnd",
                        "Job ID": job_id,
                        "Completion Time": current_start + 1_000,
                        "Job Result": {"Result": "JobSucceeded"},
                    }
                )
                job_id += 1
                stage_id += 1

    events.extend(
        [
            {
                "Event": "org.apache.spark.sql.execution.ui.SparkListenerSQLExecutionStart",
                "executionId": 1,
                "description": "Week 6 baseline warmup-0",
                "physicalPlanDescription": "Initial SortMergeJoin plan",
            },
            {
                "Event": "org.apache.spark.sql.execution.ui.SparkListenerSQLAdaptiveExecutionUpdate",
                "executionId": 1,
                "physicalPlanDescription": "Final SortMergeJoin with Exchange plan",
            },
            {
                "Event": "org.apache.spark.sql.execution.ui.SparkListenerSQLExecutionStart",
                "executionId": 2,
                "description": "Week 6 broadcast_candidate warmup-0",
                "physicalPlanDescription": "Initial BroadcastHashJoin plan",
            },
            {
                "Event": "org.apache.spark.sql.execution.ui.SparkListenerSQLAdaptiveExecutionUpdate",
                "executionId": 2,
                "physicalPlanDescription": "Final BroadcastHashJoin plan",
            },
        ]
    )
    event_file = tmp_path / "local-fixture.json"
    event_file.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )
    manifest_hash = "a" * 64

    report = recover_benchmark_report(
        event_log=event_file,
        output_dir=tmp_path / "recovered",
        run_id="fixture-run",
        source_manifest_sha256=manifest_hash,
        input_rows=100,
        spark_version="3.5.9",
        shuffle_partitions=96,
        warmups=1,
        repetitions=5,
    )

    assert report["event_log"]["benchmark_groups"] == 12
    assert report["variants"]["baseline"]["timed_runs_seconds"] == [1.0] * 5
    assert report["experiment"]["physical_plan_evidence"][
        "baseline_sort_merge_join_present"
    ]
    assert report["experiment"]["physical_plan_evidence"][
        "candidate_broadcast_hash_join_present"
    ]
    assert report["experiment"]["correctness_parity"]["status"] == (
        "PENDING_TOLERANCE_RECHECK"
    )
    assert (tmp_path / "recovered" / "benchmark_context.json").is_file()
