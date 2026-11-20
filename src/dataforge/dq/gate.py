"""Great Expectations G1 checks for an isolated weather landing dataset."""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .results import (
    DQResult,
    ResultSink,
    add_result_context,
    cloud_sink_from_env,
    make_result,
    new_run_id,
    require_isolated_dataset,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "quality" / "gx" / "weather_landing.yml"


@dataclass(frozen=True)
class GateReport:
    run_id: str
    layer: str
    dataset: str
    observation_date: str
    enforce: str
    results: tuple[DQResult, ...]
    blocked: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "layer": self.layer,
            "dataset": self.dataset,
            "date": self.observation_date,
            "enforce": self.enforce,
            "blocked": self.blocked,
            "checks": [row.as_row() for row in self.results],
        }


def _read_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    import yaml

    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _gx_batch(frame):
    import great_expectations as gx

    context = gx.get_context(mode="ephemeral")
    datasource = context.data_sources.add_pandas(name="dataforge_w9_landing")
    asset = datasource.add_dataframe_asset(name="weather_landing")
    definition = asset.add_batch_definition_whole_dataframe("whole_landing_frame")
    return definition.get_batch(batch_parameters={"dataframe": frame})


def _expect(batch, expectation) -> tuple[bool, int, str]:
    # GX emits progress output for individual DataFrame expectations. Keep the
    # CLI contract to one structured result and use the returned result object.
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        result = batch.validate(expectation)
    details = result.result or {}
    count = details.get("unexpected_count")
    if count is None:
        count = 0 if result.success else 1
    observed = {
        "unexpected_count": int(count),
        "observed_value": details.get("observed_value"),
    }
    return bool(result.success), int(count), json.dumps(observed, sort_keys=True, default=str)


def _field_is_nullable(field: object) -> bool | None:
    if isinstance(field, dict):
        mode = field.get("mode")
        return mode == "NULLABLE" if mode else field.get("nullable")
    mode = getattr(field, "mode", None)
    if mode:
        return mode == "NULLABLE"
    return getattr(field, "nullable", None)


def _result(
    *,
    run_id: str,
    check_id: str,
    severity: str,
    passed: bool,
    observed: object,
    threshold: object,
    failing_rows: int,
    contract_version: str,
    status: str | None = None,
) -> DQResult:
    return make_result(
        run_id=run_id,
        check_id=check_id,
        layer="G1",
        severity=severity,
        status=status or ("PASS" if passed else "FAIL"),
        observed=observed,
        threshold=threshold,
        failing_rows=failing_rows,
        contract_version=contract_version,
    )


def run_landing_gate(
    frame,
    *,
    dataset: str,
    observation_date: date,
    enforce: str = "warn",
    schema_fields: dict[str, object] | None = None,
    result_sink: ResultSink | None = None,
    config_path: Path = CONFIG_PATH,
) -> GateReport:
    """Run catalog-owned G1 checks with GX and persist a summary per check."""
    import great_expectations.expectations as gxe
    import pandas as pd

    require_isolated_dataset(dataset)
    if enforce not in {"warn", "block"}:
        raise ValueError("DQ_ENFORCE must be 'warn' or 'block'")
    config = _read_config(config_path)
    checks = config["checks"]
    contract_version = str(config["contract_version"])
    run_id = new_run_id()
    results: list[DQResult] = []
    schema_fields = schema_fields or {}
    batch = _gx_batch(frame)
    columns = set(frame.columns)

    schema_cfg = checks["schema"]
    expected_columns = schema_cfg["required_columns"]
    expectation_passes: list[bool] = []
    expectation_failures = 0
    schema_messages: list[str] = []
    if columns:
        ok, count, message = _expect(
            batch,
            gxe.ExpectTableColumnsToMatchSet(
                column_set=list(expected_columns),
                exact_match=False,
                result_format={"result_format": "SUMMARY"},
            ),
        )
        expectation_passes.append(ok)
        expectation_failures += count
        if not ok:
            schema_messages.append("required_columns_missing_or_extra_shape")
    else:
        expectation_passes.append(False)
        expectation_failures += 1
        schema_messages.append("table_has_no_columns")

    for column, expected_type in expected_columns.items():
        if column not in columns:
            expectation_passes.append(False)
            expectation_failures += 1
            schema_messages.append(f"missing:{column}")
            continue
        if expected_type == "str":
            # Pandas 2 represents parquet strings as object dtype; Pandas 3 uses
            # its dedicated str dtype. Validate the logical value type across
            # both representations instead of pinning the check to one dtype.
            # Nulls remain governed by the contract's separate null checks.
            expectation = gxe.ExpectColumnValuesToBeOfType(
                column=column,
                type_="str",
                result_format={"result_format": "SUMMARY"},
            )
        else:
            expectation = gxe.ExpectColumnTypeToBe(
                column=column,
                type_=expected_type,
                result_format={"result_format": "SUMMARY"},
            )
        ok, count, _ = _expect(batch, expectation)
        expectation_passes.append(ok)
        expectation_failures += count or (0 if ok else 1)
        if not ok:
            schema_messages.append(f"type_mismatch:{column}")

    for column in schema_cfg.get("required_non_null", []):
        if column not in columns:
            continue
        ok, count, _ = _expect(
            batch,
            gxe.ExpectColumnValuesToNotBeNull(
                column=column,
                result_format={"result_format": "SUMMARY"},
            ),
        )
        expectation_passes.append(ok)
        expectation_failures += count or (0 if ok else 1)
        if not ok:
            schema_messages.append(f"missing_values:{column}")

    extras = sorted(columns - set(expected_columns))
    non_nullable_extras: list[str] = []
    nullable_extras: list[str] = []
    for column in extras:
        nullable = _field_is_nullable(schema_fields.get(column))
        if nullable is None:
            nullable = bool(frame[column].isna().all())
        (nullable_extras if nullable else non_nullable_extras).append(column)

    schema_passed = all(expectation_passes) and not non_nullable_extras
    if non_nullable_extras:
        schema_messages.extend(f"unexpected_required:{name}" for name in non_nullable_extras)
        expectation_failures += len(non_nullable_extras)
    results.append(
        _result(
            run_id=run_id,
            check_id=schema_cfg["check_id"],
            severity=schema_cfg["severity"],
            passed=schema_passed,
            observed={"issues": schema_messages, "required_columns": len(expected_columns)},
            threshold={
                "required_columns": "present with contracted logical/physical types and required non-null values"
            },
            failing_rows=expectation_failures,
            contract_version=contract_version,
        )
    )

    additive_cfg = checks["schema_additive"]
    additive_warning = bool(nullable_extras)
    results.append(
        _result(
            run_id=run_id,
            check_id=additive_cfg["check_id"],
            severity=additive_cfg["severity"],
            passed=not additive_warning,
            status="WARN" if additive_warning else "PASS",
            observed={"nullable_additions": nullable_extras},
            threshold={"unknown_nullable_columns": "warn and publish"},
            failing_rows=0,
            contract_version=contract_version,
        )
    )

    def add_check(check_cfg, outcome: tuple[bool, int, str], threshold: object) -> None:
        passed, count, observed = outcome
        results.append(
            _result(
                run_id=run_id,
                check_id=check_cfg["check_id"],
                severity=check_cfg["severity"],
                passed=passed,
                observed=observed,
                threshold=threshold,
                failing_rows=count,
                contract_version=contract_version,
            )
        )

    province_cfg = checks["province_id_not_null"]
    if province_cfg["column"] in columns:
        add_check(
            province_cfg,
            _expect(
                batch,
                gxe.ExpectColumnValuesToNotBeNull(
                    column=province_cfg["column"],
                    result_format={"result_format": "SUMMARY"},
                ),
            ),
            "no null province_id values",
        )

    grain_cfg = checks["grain_unique"]
    if set(grain_cfg["columns"]).issubset(columns):
        add_check(
            grain_cfg,
            _expect(
                batch,
                gxe.ExpectCompoundColumnsToBeUnique(
                    column_list=grain_cfg["columns"],
                    ignore_row_if="never",
                    result_format={"result_format": "SUMMARY"},
                ),
            ),
            {"unique_columns": grain_cfg["columns"]},
        )

    range_cfg = checks["physical_range"]
    range_results: list[tuple[bool, int, str]] = []
    if "precipitation_mm" in columns:
        range_results.append(
            _expect(
                batch,
                gxe.ExpectColumnValuesToBeBetween(
                    column="precipitation_mm",
                    min_value=range_cfg["precipitation_mm"]["min"],
                    result_format={"result_format": "SUMMARY"},
                ),
            )
        )
    if "temp_max_c" in columns:
        range_results.append(
            _expect(
                batch,
                gxe.ExpectColumnValuesToBeBetween(
                    column="temp_max_c",
                    min_value=range_cfg["temp_max_c"]["min"],
                    max_value=range_cfg["temp_max_c"]["max"],
                    result_format={"result_format": "SUMMARY"},
                ),
            )
        )
    if range_results:
        add_check(
            range_cfg,
            (
                all(item[0] for item in range_results),
                sum(item[1] for item in range_results),
                json.dumps([json.loads(item[2]) for item in range_results], sort_keys=True),
            ),
            range_cfg,
        )

    domain_cfg = checks["province_domain"]
    if domain_cfg["column"] in columns:
        add_check(
            domain_cfg,
            _expect(
                batch,
                gxe.ExpectColumnValuesToBeInSet(
                    column=domain_cfg["column"],
                    value_set=domain_cfg["values"],
                    result_format={"result_format": "SUMMARY"},
                ),
            ),
            {"allowed_values": domain_cfg["values"]},
        )

    dates_cfg = checks["rows_per_date"]
    if "observation_date" in columns:
        observed_dates = sorted(
            {str(value) for value in frame["observation_date"].dropna().tolist()}
        )
        if not observed_dates:
            observed_dates = [observation_date.isoformat()]
        date_results = []
        for date_value in observed_dates:
            day_frame = frame.loc[frame["observation_date"].astype(str) == date_value]
            day_batch = _gx_batch(day_frame)
            date_results.append(
                _expect(
                    day_batch,
                    gxe.ExpectTableRowCountToEqual(
                        value=dates_cfg["expected"],
                        result_format={"result_format": "SUMMARY"},
                    ),
                )
            )
        add_check(
            dates_cfg,
            (
                all(item[0] for item in date_results),
                sum(item[1] for item in date_results),
                json.dumps(
                    {date_value: int(count) for date_value, (_, count, _) in zip(observed_dates, date_results)},
                    sort_keys=True,
                ),
            ),
            {"rows_per_date": dates_cfg["expected"]},
        )

    future_cfg = checks["no_future_date"]
    if future_cfg["column"] in columns:
        parsed_dates = pd.to_datetime(frame[future_cfg["column"]], errors="coerce").dt.date
        invalid_count = int(parsed_dates.isna().sum())
        future_count = int((parsed_dates.dropna() > observation_date).sum())
        results.append(
            _result(
                run_id=run_id,
                check_id=future_cfg["check_id"],
                severity=future_cfg["severity"],
                passed=invalid_count == 0 and future_count == 0,
                observed={"invalid_dates": invalid_count, "future_dates": future_count},
                threshold={"maximum_date": observation_date.isoformat()},
                failing_rows=invalid_count + future_count,
                contract_version=contract_version,
            )
        )

    unit_cfg = checks["temp_unit_range"]
    if unit_cfg["column"] in columns:
        add_check(
            unit_cfg,
            _expect(
                batch,
                gxe.ExpectColumnValuesToBeBetween(
                    column=unit_cfg["column"],
                    max_value=unit_cfg["maximum_celsius"],
                    result_format={"result_format": "SUMMARY"},
                ),
            ),
            {"maximum_celsius": unit_cfg["maximum_celsius"]},
        )

    blocking_failure = any(
        item.severity == "P1" and item.status == "FAIL" for item in results
    )
    blocked = enforce == "block" and blocking_failure
    has_warning = any(item.status in {"FAIL", "WARN"} for item in results)
    publish_action = "BLOCK" if blocked else ("PUBLISH_WITH_WARNING" if has_warning else "PUBLISH")
    results = [
        add_result_context(
            result,
            dataset=dataset,
            event_date=observation_date.isoformat(),
            publish_action=publish_action,
        )
        for result in results
    ]
    sink = result_sink or cloud_sink_from_env()
    sink.write(results)
    return GateReport(
        run_id=run_id,
        layer="G1",
        dataset=dataset,
        observation_date=observation_date.isoformat(),
        enforce=enforce,
        results=tuple(results),
        blocked=blocked,
    )


def _read_bigquery_frame(project: str, dataset: str, observation_date: date):
    from google.cloud import bigquery

    require_isolated_dataset(dataset)
    if project != "dataforge-p7-lab-d0f725":
        raise ValueError("DQ gate reads are restricted to the approved DataForge project")
    client = bigquery.Client(project=project)
    table_id = f"{project}.{dataset}.weather_landing"
    table = client.get_table(table_id)
    fields = {field.name: field for field in table.schema}
    query = (
        f"SELECT * FROM `{table_id}` "
        "WHERE observation_date = @observation_date"
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("observation_date", "DATE", observation_date)
        ],
        maximum_bytes_billed=1024**3,
        labels={"application": "dataforge", "phase": "week9", "action": "dq-gate"},
    )
    job = client.query(query, job_config=job_config, location="us-central1")
    frame = job.to_dataframe(create_bqstorage_client=False)
    usage_path = os.environ.get("DATAFORGE_W9_COST_USAGE_FILE")
    if usage_path:
        job_id = getattr(job, "job_id", None)
        bytes_billed = getattr(job, "total_bytes_billed", None)
        if (
            not isinstance(job_id, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", job_id) is None
            or isinstance(bytes_billed, bool)
            or not isinstance(bytes_billed, int)
            or bytes_billed < 0
        ):
            raise RuntimeError("G1 BigQuery usage metadata is unavailable for the run-cost guard")
        usage = {"job_id": job_id, "bytes_billed": bytes_billed}
        destination = Path(usage_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(usage, sort_keys=True), encoding="utf-8")
    return frame, fields


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    gate = subparsers.add_parser("gate", help="run a quality gate")
    gate.add_argument("--layer", choices=["landing"], required=True)
    gate.add_argument("--dataset", required=True)
    gate.add_argument("--date", required=True, dest="observation_date")
    args = parser.parse_args(argv)
    try:
        parsed_date = date.fromisoformat(args.observation_date)
        if parsed_date.isoformat() != args.observation_date:
            raise ValueError("date must use canonical YYYY-MM-DD")
        require_isolated_dataset(args.dataset)
        project = os.environ.get("DATAFORGE_PROJECT_ID", "dataforge-p7-lab-d0f725")
        frame, schema_fields = _read_bigquery_frame(project, args.dataset, parsed_date)
        report = run_landing_gate(
            frame,
            dataset=args.dataset,
            observation_date=parsed_date,
            enforce=os.environ.get("DQ_ENFORCE", "warn"),
            schema_fields=schema_fields,
        )
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(report.as_dict(), sort_keys=True))
    return 1 if report.blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
