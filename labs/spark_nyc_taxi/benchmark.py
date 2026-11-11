"""Controlled broadcast-versus-shuffle benchmark and Spark event-log receipt."""

from __future__ import annotations

import json
import math
import statistics
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class BenchmarkSettings:
    """Execution controls shared by both join candidates."""

    warmups: int = 1
    repetitions: int = 5
    shuffle_partitions: int = 96
    adaptive_enabled: bool = True

    def validate(self) -> None:
        if self.warmups < 1:
            raise ValueError("at least one warmup is required")
        if self.repetitions < 1:
            raise ValueError("at least one timed repetition is required")
        if self.shuffle_partitions < 1:
            raise ValueError("shuffle_partitions must be positive")


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "asDict"):
        return {key: _json_value(item) for key, item in value.asDict(recursive=True).items()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _stable_summary(frame: Any) -> dict[str, Any]:
    """Force every output metric while returning only one small driver row."""
    from pyspark.sql import functions as F

    required = {
        "trip_count",
        "distance_miles_sum",
        "fare_amount_sum",
        "total_amount_sum",
        "duration_p50_minutes",
        "duration_p95_minutes",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"aggregate output is missing benchmark columns: {missing}")

    summary = (
        frame.agg(
            F.count(F.lit(1)).alias("aggregate_group_count"),
            F.sum("trip_count").alias("accepted_trip_count"),
            F.sum("distance_miles_sum").alias("distance_miles_sum"),
            F.sum("fare_amount_sum").alias("fare_amount_sum"),
            F.sum("total_amount_sum").alias("total_amount_sum"),
            F.sum("duration_p50_minutes").alias("duration_p50_sum_minutes"),
            F.sum("duration_p95_minutes").alias("duration_p95_sum_minutes"),
        )
        .first()
    )
    return {key: _json_value(value) for key, value in summary.asDict().items()}


def _capture_formatted_plan(frame: Any) -> str:
    """Capture Spark's formatted physical plan before the timed action."""
    from contextlib import redirect_stdout
    from io import StringIO

    output = StringIO()
    with redirect_stdout(output):
        frame.explain(mode="formatted")
    return output.getvalue()


def _executed_plan(frame: Any) -> str:
    try:
        return frame._jdf.queryExecution().executedPlan().toString()
    except Exception as exc:  # pragma: no cover - Py4J error shape varies by Spark patch
        return f"UNAVAILABLE: {type(exc).__name__}: {exc}"


def _compare_aggregate_frames(
    left: Any,
    right: Any,
    *,
    duration_tolerance_minutes: float,
) -> dict[str, Any]:
    """Compare exact grain/count/money values and bounded approximate percentiles."""
    from pyspark.sql import functions as F

    keys = ("pickup_date", "pickup_hour", "pickup_zone", "pickup_borough")
    exact_fields = (
        "trip_count",
        "distance_miles_sum",
        "fare_amount_sum",
        "total_amount_sum",
    )
    percentile_fields = ("duration_p50_minutes", "duration_p95_minutes")
    joined = left.alias("left").join(
        right.alias("right"),
        [F.col(f"left.{key}").eqNullSafe(F.col(f"right.{key}")) for key in keys],
        "full_outer",
    )
    missing_key = F.col("left.pickup_date").isNull() | F.col("right.pickup_date").isNull()

    exact_mismatch = F.lit(False)
    for field in exact_fields:
        exact_mismatch = exact_mismatch | ~F.col(f"left.{field}").eqNullSafe(
            F.col(f"right.{field}")
        )

    percentile_mismatch = F.lit(False)
    percentile_deltas: dict[str, Any] = {}
    for field in percentile_fields:
        left_value = F.col(f"left.{field}")
        right_value = F.col(f"right.{field}")
        difference = F.abs(left_value - right_value)
        percentile_mismatch = percentile_mismatch | (
            (left_value.isNull() != right_value.isNull())
            | (left_value.isNotNull()
               & right_value.isNotNull()
               & (difference > F.lit(duration_tolerance_minutes)))
        )
        percentile_deltas[field] = difference

    summary = joined.agg(
        F.count(F.lit(1)).alias("joined_rows"),
        F.sum(F.when(missing_key, 1).otherwise(0)).alias("unmatched_key_rows"),
        F.sum(F.when(exact_mismatch, 1).otherwise(0)).alias("exact_metric_mismatch_rows"),
        F.sum(F.when(percentile_mismatch, 1).otherwise(0)).alias(
            "percentile_tolerance_mismatch_rows"
        ),
        *[
            F.max(F.coalesce(percentile_deltas[field], F.lit(0.0))).alias(
                f"max_{field}_delta_minutes"
            )
            for field in percentile_fields
        ],
    ).first()
    result = {
        key: (value if value is not None else 0)
        for key, value in summary.asDict().items()
    }
    result.update(
        {
            "status": (
                "PASS"
                if result["unmatched_key_rows"] == 0
                and result["exact_metric_mismatch_rows"] == 0
                and result["percentile_tolerance_mismatch_rows"] == 0
                else "FAIL"
            ),
            "key_columns": list(keys),
            "exact_columns": list(exact_fields),
            "approximate_columns": list(percentile_fields),
            "percentile_tolerance_minutes": duration_tolerance_minutes,
            "checked_outside_timed_intervals": True,
        }
    )
    return result


def _event_log_path(spark: Any, override: str | Path | None) -> Path | None:
    if override is not None:
        return Path(override)
    try:
        uri = spark.sparkContext.getConf().get("spark.eventLog.dir")
    except Exception:
        return None
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if not parsed.scheme:
        return Path(uri)
    return None


def _event_property_map(properties: Any) -> dict[str, Any]:
    if isinstance(properties, dict):
        return properties
    if isinstance(properties, list):
        return {str(key): value for key, value in properties if isinstance(key, str)}
    return {}


def _pick(mapping: Any, *names: str, default: Any = 0) -> Any:
    if not isinstance(mapping, dict):
        return default
    for name in names:
        if name in mapping:
            value = mapping[name]
            if value is not None:
                return value
    return default


def _read_events(event_dir: Path | None) -> tuple[list[dict[str, Any]], list[str], str | None]:
    if event_dir is None:
        return [], [], "Spark event-log directory is not configured"
    if not event_dir.exists():
        return [], [], f"Spark event-log directory is missing: {event_dir}"
    paths = sorted(
        path
        for path in event_dir.iterdir()
        if path.is_file() and (path.name.endswith(".inprogress") or not path.name.endswith(".lz4"))
    )
    events: list[dict[str, Any]] = []
    opened_paths: list[str] = []
    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as exc:
                        return events, opened_paths, f"invalid JSON in {path.name}:{line_number}: {exc}"
                    if isinstance(event, dict):
                        events.append(event)
            opened_paths.append(str(path))
        except OSError as exc:
            return events, opened_paths, f"could not read event log {path}: {exc}"
    if not opened_paths:
        return events, [], "no readable uncompressed Spark event-log files were found"
    return events, opened_paths, None


def _event_metrics_by_group(
    events: Iterable[dict[str, Any]], group_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    requested = set(group_ids)
    stage_groups: dict[int, set[str]] = defaultdict(set)
    tasks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    jobs_found: dict[str, int] = defaultdict(int)

    for event in events:
        kind = event.get("Event")
        if kind == "SparkListenerJobStart":
            properties = _event_property_map(event.get("Properties"))
            group_id = properties.get("spark.jobGroup.id")
            if group_id in requested:
                jobs_found[str(group_id)] += 1
                for stage in event.get("Stage Infos", []):
                    stage_id = _pick(stage, "Stage ID", "stageId", default=None)
                    if stage_id is not None:
                        stage_groups[int(stage_id)].add(str(group_id))
        elif kind == "SparkListenerTaskEnd":
            reason = event.get("Task End Reason")
            if isinstance(reason, dict):
                reason = reason.get("Reason")
            if reason not in (None, "Success"):
                continue
            stage_id = _pick(event, "Stage ID", "Stage Id", default=None)
            if stage_id is None:
                continue
            groups = stage_groups.get(int(stage_id), set())
            if len(groups) != 1:
                continue
            group_id = next(iter(groups))
            if group_id not in requested:
                continue

            task_info = event.get("Task Info", {})
            metrics = event.get("Task Metrics", {})
            shuffle_read = metrics.get("Shuffle Read Metrics", {})
            shuffle_write = metrics.get("Shuffle Write Metrics", {})
            input_metrics = metrics.get("Input Metrics", {})
            output_metrics = metrics.get("Output Metrics", {})
            tasks[group_id].append(
                {
                    "duration_ms": int(_pick(task_info, "Duration", "duration", default=0)),
                    "executor_run_time_ms": int(
                        _pick(metrics, "Executor Run Time", "executorRunTime", default=0)
                    ),
                    "executor_cpu_time_ns": int(
                        _pick(metrics, "Executor CPU Time", "executorCpuTime", default=0)
                    ),
                    "jvm_gc_time_ms": int(_pick(metrics, "JVM GC Time", "jvmGCTime", default=0)),
                    "memory_bytes_spilled": int(
                        _pick(metrics, "Memory Bytes Spilled", "memoryBytesSpilled", default=0)
                    ),
                    "disk_bytes_spilled": int(
                        _pick(metrics, "Disk Bytes Spilled", "diskBytesSpilled", default=0)
                    ),
                    "shuffle_read_bytes": int(
                        _pick(shuffle_read, "Remote Bytes Read", "remoteBytesRead", default=0)
                    )
                    + int(_pick(shuffle_read, "Local Bytes Read", "localBytesRead", default=0)),
                    "shuffle_read_records": int(
                        _pick(shuffle_read, "Total Records Read", "recordsRead", default=0)
                    ),
                    "shuffle_write_bytes": int(
                        _pick(
                            shuffle_write,
                            "Shuffle Bytes Written",
                            "shuffleBytesWritten",
                            default=0,
                        )
                    ),
                    "shuffle_write_records": int(
                        _pick(
                            shuffle_write,
                            "Shuffle Records Written",
                            "shuffleRecordsWritten",
                            default=0,
                        )
                    ),
                    "input_bytes": int(_pick(input_metrics, "Bytes Read", "bytesRead", default=0)),
                    "input_records": int(
                        _pick(input_metrics, "Records Read", "recordsRead", default=0)
                    ),
                    "output_bytes": int(
                        _pick(output_metrics, "Bytes Written", "bytesWritten", default=0)
                    ),
                    "output_records": int(
                        _pick(output_metrics, "Records Written", "recordsWritten", default=0)
                    ),
                }
            )

    numeric_fields = (
        "executor_run_time_ms",
        "executor_cpu_time_ns",
        "jvm_gc_time_ms",
        "memory_bytes_spilled",
        "disk_bytes_spilled",
        "shuffle_read_bytes",
        "shuffle_read_records",
        "shuffle_write_bytes",
        "shuffle_write_records",
        "input_bytes",
        "input_records",
        "output_bytes",
        "output_records",
    )
    output: dict[str, dict[str, Any]] = {}
    for group_id in requested:
        group_tasks = tasks.get(group_id, [])
        durations = sorted(task["duration_ms"] for task in group_tasks)
        med = statistics.median(durations) if durations else None
        output[group_id] = {
            "status": "CAPTURED" if group_tasks else "NOT_AVAILABLE",
            "jobs": jobs_found.get(group_id, 0),
            "successful_tasks": len(group_tasks),
            "sum_task_metrics": {
                field: sum(task[field] for task in group_tasks) for field in numeric_fields
            },
            "task_duration_ms": {
                "min": min(durations) if durations else None,
                "median": med,
                "p95": (
                    durations[max(0, math.ceil(len(durations) * 0.95) - 1)]
                    if durations
                    else None
                ),
                "max": max(durations) if durations else None,
                "max_to_median_ratio": (
                    max(durations) / med if durations and med else None
                ),
            },
        }
    return output


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    temporary.replace(path)


def run_benchmark(
    spark: Any,
    accepted: Any,
    zone_lookup: Any,
    output_dir: str | Path,
    *,
    settings: BenchmarkSettings | None = None,
    event_log_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the same aggregate once warm and repeatedly under two join plans.

    The sole controlled change is the location-lookup join strategy: baseline
    has no broadcast hint and the session disables automatic broadcasting;
    candidate applies an explicit broadcast hint. Input preparation, AQE,
    shuffle partition count, result metrics and action are identical. No cache
    is introduced. Full result parity is checked outside timed intervals.
    """
    try:
        from .transforms import aggregate_dataframe
    except ImportError:  # Support direct `python benchmark.py` execution.
        from transforms import aggregate_dataframe

    settings = settings or BenchmarkSettings()
    settings.validate()
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    run_records: dict[str, list[dict[str, Any]]] = {"baseline": [], "broadcast_candidate": []}
    plans: dict[str, str] = {}
    exact_parity: dict[str, Any] = {"status": "NOT_CHECKED"}
    group_ids: list[str] = []

    def execute_once(variant: str, *, warmup_index: int | None, repetition: int | None) -> Any:
        broadcast = variant == "broadcast_candidate"
        result = aggregate_dataframe(accepted, zone_lookup, broadcast_lookup=broadcast)
        plan_key = variant
        if plan_key not in plans:
            plans[plan_key] = _capture_formatted_plan(result)

        run_kind = f"warmup-{warmup_index}" if warmup_index is not None else f"run-{repetition}"
        group_id = f"week6-{variant}-{run_kind}-{uuid.uuid4().hex[:10]}"
        group_ids.append(group_id)
        sc = spark.sparkContext
        sc.setJobGroup(group_id, f"Week 6 {variant} {run_kind}", interruptOnCancel=True)
        started = time.perf_counter()
        try:
            summary = _stable_summary(result)
            elapsed = time.perf_counter() - started
        finally:
            sc.setLocalProperty("spark.jobGroup.id", None)
            sc.setLocalProperty("spark.job.description", None)
            sc.setLocalProperty("spark.job.interruptOnCancel", None)
        executed = _executed_plan(result)
        record = {
            "group_id": group_id,
            "kind": "warmup" if warmup_index is not None else "timed",
            "index": warmup_index if warmup_index is not None else repetition,
            "elapsed_seconds": round(elapsed, 6),
            "summary": summary,
            "executed_plan": executed,
        }
        run_records[variant].append(record)
        return result

    final_result: dict[str, Any] = {}
    for warmup in range(settings.warmups):
        execute_once("baseline", warmup_index=warmup, repetition=None)
        execute_once("broadcast_candidate", warmup_index=warmup, repetition=None)

    order = ("baseline", "broadcast_candidate")
    for repetition in range(settings.repetitions):
        candidates = order if repetition % 2 == 0 else tuple(reversed(order))
        for variant in candidates:
            final_result[variant] = execute_once(
                variant, warmup_index=None, repetition=repetition
            )

    baseline_summary = run_records["baseline"][-1]["summary"]
    candidate_summary = run_records["broadcast_candidate"][-1]["summary"]
    exact_summary_fields = (
        "aggregate_group_count",
        "accepted_trip_count",
        "distance_miles_sum",
        "fare_amount_sum",
        "total_amount_sum",
    )
    summary_differences = {
        field: {
            "baseline": baseline_summary[field],
            "candidate": candidate_summary[field],
        }
        for field in exact_summary_fields
        if baseline_summary[field] != candidate_summary[field]
    }
    if summary_differences:
        raise AssertionError(
            f"baseline and broadcast candidate differ on exact reconciliation metrics: "
            f"{summary_differences}"
        )
    percentile_summary_deltas = {
        field: abs(float(baseline_summary[field] or 0) - float(candidate_summary[field] or 0))
        for field in ("duration_p50_sum_minutes", "duration_p95_sum_minutes")
    }
    duration_tolerance_minutes = 1.0
    exact_parity = _compare_aggregate_frames(
        final_result["baseline"],
        final_result["broadcast_candidate"],
        duration_tolerance_minutes=duration_tolerance_minutes,
    )

    plan_texts: dict[str, str] = {}
    for variant in run_records:
        executed = run_records[variant][-1]["executed_plan"]
        plan_texts[variant] = plans[variant] + "\n\n--- Executed plan after timed action ---\n" + executed
    (target_dir / "spark_plan_baseline.txt").write_text(plan_texts["baseline"], encoding="utf-8")
    (target_dir / "spark_plan_candidate.txt").write_text(
        plan_texts["broadcast_candidate"], encoding="utf-8"
    )

    plan_evidence = {
        "baseline_exchange_present": "Exchange" in plan_texts["baseline"],
        "candidate_broadcast_hash_join_present": "BroadcastHashJoin"
        in plan_texts["broadcast_candidate"],
        "baseline_broadcast_hash_join_present": "BroadcastHashJoin" in plan_texts["baseline"],
    }
    event_dir = _event_log_path(spark, event_log_dir)
    try:
        spark.sparkContext._jsc.sc().listenerBus().waitUntilEmpty(30_000)
    except Exception:
        pass
    events, event_paths, event_error = _read_events(event_dir)
    event_metrics = _event_metrics_by_group(events, group_ids)

    variant_results: dict[str, Any] = {}
    speedup = None
    for variant, records in run_records.items():
        timed = [record for record in records if record["kind"] == "timed"]
        durations = [record["elapsed_seconds"] for record in timed]
        median = statistics.median(durations)
        variant_results[variant] = {
            "warmup_count": sum(record["kind"] == "warmup" for record in records),
            "timed_runs_seconds": durations,
            "median_seconds": median,
            "min_seconds": min(durations),
            "max_seconds": max(durations),
            "range_seconds": max(durations) - min(durations),
            "run_receipts": [
                {
                    "group_id": record["group_id"],
                    "kind": record["kind"],
                    "index": record["index"],
                    "elapsed_seconds": record["elapsed_seconds"],
                    "summary": record["summary"],
                    "spark_event_metrics": event_metrics.get(
                        record["group_id"], {"status": "NOT_AVAILABLE"}
                    ),
                }
                for record in records
            ],
        }
        if variant == "baseline":
            speedup = median
        elif variant == "broadcast_candidate" and speedup:
            speedup = speedup / median

    report = {
        "status": "LOCAL_MEASURED",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "spark_version": spark.version,
            "master": spark.sparkContext.master,
            "application_id": spark.sparkContext.applicationId,
            "session_timezone": spark.conf.get("spark.sql.session.timeZone"),
            "adaptive_enabled": settings.adaptive_enabled,
            "shuffle_partitions": settings.shuffle_partitions,
            "automatic_broadcast_threshold": spark.conf.get(
                "spark.sql.autoBroadcastJoinThreshold", "UNSET"
            ),
            "adaptive_broadcast_threshold": spark.conf.get(
                "spark.sql.adaptive.autoBroadcastJoinThreshold", "UNSET"
            ),
            "cache_policy": "No DataFrame cache is used by this harness.",
        },
        "experiment": {
            "controlled_change": "explicit broadcast hint on the small taxi-zone lookup",
            "baseline": "automatic broadcast disabled; no broadcast hint",
            "candidate": "same input and action; explicit broadcast hint",
            "warmups_per_variant": settings.warmups,
            "timed_repetitions_per_variant": settings.repetitions,
            "input_preparation": "same accepted DataFrame and same zone lookup for every run",
            "measured_action": "aggregate one-row reconciliation summary including every output metric",
            "correctness_parity": exact_parity,
            "approximate_percentile_summary_deltas_minutes": percentile_summary_deltas,
            "physical_plan_evidence": plan_evidence,
            "median_baseline_over_candidate_ratio": speedup,
            "speedup_claim": (
                "Exploratory comparison of recorded medians; interpret with event metrics and local-machine limits."
                if speedup is not None
                else "NOT_AVAILABLE"
            ),
        },
        "variants": variant_results,
        "event_log": {
            "directory": str(event_dir) if event_dir else None,
            "files": event_paths,
            "events_read": len(events),
            "status": "CAPTURED" if event_paths else "NOT_AVAILABLE",
            "reason": event_error,
        },
        "ui": {
            "url": "http://localhost:4040",
            "status": "AVAILABLE_WHILE_SPARK_APPLICATION_IS_RUNNING",
            "capture_status": "SCREENSHOT_NOT_CAPTURED_BY_BENCHMARK_HARNESS",
        },
        "limitations": [
            "This is a single-machine local Spark result, not a cluster-scale performance claim.",
            "Task metrics are event-log-derived and are marked NOT_AVAILABLE when group attribution fails.",
            "The host filesystem cache can warm across repetitions; the first measured run is not treated as a cold read.",
        ],
    }
    _write_json(target_dir / "benchmark.json", report)
    if exact_parity["status"] != "PASS":
        raise AssertionError(f"full aggregate outputs differ: {exact_parity}")
    if not plan_evidence["candidate_broadcast_hash_join_present"]:
        raise AssertionError("candidate plan did not show the requested BroadcastHashJoin")
    if plan_evidence["baseline_broadcast_hash_join_present"]:
        raise AssertionError("baseline plan unexpectedly used a BroadcastHashJoin")
    return report
