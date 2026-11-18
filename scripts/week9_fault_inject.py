"""Run local, fixture-only Week 9 faults against captured weather data."""
# ruff: noqa: E402 -- bootstrap the source-tree imports from a direct script run.
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

# Run from a checkout without requiring the package to be installed.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "week9"))

import pandas as pd
import requests
import yaml
from faults.cases import mutate_landing_frame

from cloud.jobs.week7_weather.validation import (
    PayloadValidationError,
    validate_open_meteo_response,
)
from dataforge.dq.gate import run_landing_gate
from dataforge.dq.results import MemoryResultSink
from dataforge.dq.wap import initialize_published, write_audit_publish
from dataforge.weather import fetch

MANIFEST_PATH = ROOT / "tests" / "week9" / "faults" / "manifest.yml"
CAPTURE_PATH = ROOT / "tests" / "week9" / "faults" / "weather_7date_slice.parquet"
API_CAPTURE_PATH = (
    ROOT / "tests" / "week9" / "faults" / "captures" / "open_meteo_hcm_2026-11-05.json"
)
REPORT_PATH = ROOT / "tests" / "week9" / "fault_matrix_report.md"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest() -> dict:
    with MANIFEST_PATH.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def load_api_capture() -> tuple[bytes, dict]:
    raw = API_CAPTURE_PATH.read_bytes()
    return raw, json.loads(raw)


def run_landing_fault(
    fault_id: str,
    dataset: str,
    clean_frame: pd.DataFrame,
    definition: dict,
    persistent_root: Path | None = None,
) -> dict:
    injected_at = now()
    candidate = mutate_landing_frame(fault_id, clean_frame)
    sink = MemoryResultSink()
    gate = run_landing_gate(
        candidate,
        dataset=dataset,
        observation_date=date.today(),
        enforce="block",
        result_sink=sink,
    )
    detector = definition["check_id"]
    expected_ids = [
        part.strip()
        for part in detector.split("+")
        if part.strip().startswith("G1.")
    ]
    gate_rows = [
        row
        for row in sink.results
        if row.check_id in expected_ids and row.status in {"FAIL", "WARN", "NOOP"}
    ]
    if fault_id == "F09":
        replay_row = next(
            (row for row in gate_rows if row.check_id == "G1.LANDING.IDEMPOTENCY_REPLAY"),
            None,
        )
        if replay_row:
            raise AssertionError("idempotency event must be recorded only by the publish audit")

    def apply_local_wap(drill_root: Path):
        published_path = drill_root / "published" / "weather_landing.parquet"
        if not published_path.is_file():
            initialize_published(drill_root, clean_frame)
        before_hash = sha256(published_path)
        publish_result = write_audit_publish(
            drill_root,
            run_id,
            candidate,
            gate,
            result_sink=sink,
        )
        after_hash = sha256(published_path)
        return before_hash, after_hash, publish_result

    run_id = f"{fault_id.lower().replace('-', '')}-{datetime.now().strftime('%H%M%S%f')}"
    if persistent_root is not None:
        if persistent_root.name != dataset:
            raise ValueError("persistent root directory name must match --dataset")
        before, after, publish = apply_local_wap(persistent_root)
        manifest_base = (
            persistent_root / "quarantine" / run_id
            if publish["action"] == "BLOCK"
            else persistent_root / "manifests"
        )
        manifest_path = (
            manifest_base / "manifest.json"
            if publish["action"] == "BLOCK"
            else manifest_base / f"{run_id}.json"
        )
    else:
        with tempfile.TemporaryDirectory(prefix="dataforge-week9-fault-") as temp_dir:
            before, after, publish = apply_local_wap(Path(temp_dir) / dataset)
        manifest_path = None

    if fault_id == "F09":
        detected = publish.get("check_id") == "G1.LANDING.IDEMPOTENCY_REPLAY"
        action = publish["action"]
        passed = detected and action == "NO_OP" and before == after
    elif fault_id == "F-N0":
        failures = [
            row for row in sink.results
            if row.severity in {"P1", "P2"} and row.status in {"FAIL", "WARN"}
        ]
        detected = not failures
        action = publish["action"]
        passed = detected and action in {"NO_OP", "PUBLISH"} and before == after
    else:
        detected = all(
            any(row.check_id == check_id and row.status in {"FAIL", "WARN"} for row in sink.results)
            for check_id in expected_ids
        )
        if fault_id == "F05b":
            action = "WARN_PUBLISH" if publish["action"] == "PUBLISH" else publish["action"]
            passed = detected and action == "WARN_PUBLISH" and publish["status"] == "PUBLISHED"
        else:
            action = publish["action"]
            passed = detected and action == "BLOCK" and before == after

    return {
        "fault": fault_id,
        "run_id": run_id,
        "manifest_path": str(manifest_path) if manifest_path else "TEMPORARY (deleted after assertion)",
        "as_of_date": date.today().isoformat(),
        "injected_at": injected_at,
        "detector": detector,
        "detected_at": now() if detected else "UNDETECTED",
        "channel": "NOT_ATTEMPTED (local fixture)",
        "received_at": "NOT_ATTEMPTED",
        "action": action,
        "gold_hash_before": before,
        "gold_hash_after": after,
        "result": "PASS" if passed else "FAIL",
        "evidence": "unit (local captured landing fixture)",
    }


def run_g0_fault(fault_id: str, definition: dict) -> dict:
    raw, captured = load_api_capture()
    payload = copy.deepcopy(captured)
    if fault_id == "F05a":
        payload["daily_units"]["temperature_2m_max"] = "°F"
        expected_check = "G0.API.SCHEMA"
    elif fault_id == "F11":
        payload["daily"]["time"] = []
        payload["daily"]["precipitation_sum"] = []
        payload["daily"]["temperature_2m_max"] = []
        expected_check = "G0.API.RESPONSE_COMPLETENESS"
    else:
        raise ValueError(f"no G0 payload mutation for {fault_id}")
    injected_at = now()
    with tempfile.TemporaryDirectory(prefix="dataforge-week9-g0-") as temp_dir:
        drill_root = Path(temp_dir) / "w9_drill"
        clean_frame = pd.read_parquet(CAPTURE_PATH)
        before = initialize_published(drill_root, clean_frame)
        after = sha256(drill_root / "published" / "weather_landing.parquet")
    detected = False
    try:
        validate_open_meteo_response(payload, requested_dates=["2026-11-05"])
    except PayloadValidationError as exc:
        detected = exc.check_id == expected_check
    return {
        "fault": fault_id,
        "as_of_date": "2026-11-05",
        "injected_at": injected_at,
        "detector": expected_check,
        "detected_at": now() if detected else "UNDETECTED",
        "channel": "NOT_ATTEMPTED (local fixture)",
        "received_at": "NOT_ATTEMPTED",
        "action": "BLOCK_BEFORE_LANDING",
        "gold_hash_before": before,
        "gold_hash_after": after,
        "result": "PASS" if detected and before == after else "FAIL",
        "evidence": f"unit (mutation derived from captured response; {len(raw)}-byte source)",
    }


class FakeResponse:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self):
        return json.loads(self.content)


def run_transient_fault(definition: dict) -> dict:
    raw, _ = load_api_capture()
    responses = iter([FakeResponse(503, b"service unavailable"), FakeResponse(200, raw)])
    import dataforge.weather as weather_module

    previous_sleep = weather_module.time.sleep
    weather_module.time.sleep = lambda _seconds: None
    injected_at = now()
    try:
        with tempfile.TemporaryDirectory(prefix="dataforge-week9-transient-") as temp_dir:
            count = fetch(
                date(2026, 11, 5),
                date(2026, 11, 5),
                provinces=["HCM"],
                dest=Path(temp_dir),
                requester=lambda *_args, **_kwargs: next(responses),
                response_validator=lambda payload, requested, _province: validate_open_meteo_response(
                    payload, requested_dates=requested
                ),
            )
            provenance = json.loads(
                (Path(temp_dir) / ".open_meteo" / "weather_provenance.json").read_text(
                    encoding="utf-8"
                )
            )
    finally:
        weather_module.time.sleep = previous_sleep
    passed = count == 1 and [row["http_status"] for row in provenance["responses"]] == [503, 200]
    return {
        "fault": "F-T1",
        "as_of_date": "2026-11-05",
        "injected_at": injected_at,
        "detector": definition["check_id"],
        "detected_at": now() if passed else "UNDETECTED",
        "channel": "NOT_ATTEMPTED (local fixture)",
        "received_at": "NOT_ATTEMPTED",
        "action": "RETRY_THEN_SUCCEED",
        "gold_hash_before": "UNCHANGED (no publish step)",
        "gold_hash_after": "UNCHANGED (no publish step)",
        "result": "PASS" if passed else "FAIL",
        "evidence": "unit (503 followed by captured Open-Meteo response)",
    }


def run_fault(
    fault_id: str,
    dataset: str,
    manifest: dict,
    clean_frame: pd.DataFrame,
    persistent_root: Path | None = None,
) -> dict:
    definition = manifest["faults"][fault_id]
    if fault_id in {"F07", "F10"}:
        detail = (
            "F07 requires dbt source-freshness execution against an isolated BigQuery dataset."
            if fault_id == "F07"
            else "F10 requires the dbt G2 test against an isolated BigQuery dataset."
        )
        return {
            "fault": fault_id,
            "as_of_date": "UNVERIFIED",
            "injected_at": "UNVERIFIED",
            "detector": definition["check_id"],
            "detected_at": "UNVERIFIED",
            "channel": "UNVERIFIED",
            "received_at": "UNVERIFIED",
            "action": "UNVERIFIED (isolated BigQuery dataset is not provisioned)",
            "gold_hash_before": "UNVERIFIED",
            "gold_hash_after": "UNVERIFIED",
            "result": f"UNVERIFIED — {detail}",
            "evidence": "UNVERIFIED (local-only per lane constraint)",
        }
    if fault_id == "F-T1":
        return run_transient_fault(definition)
    if fault_id == "F11":
        return run_g0_fault(fault_id, definition)
    if fault_id == "F05a":
        g0 = run_g0_fault(fault_id, definition)
        g1 = run_landing_fault(fault_id, dataset, clean_frame, definition, persistent_root)
        return {
            **g1,
            "detector": definition["check_id"],
            "result": "PASS" if g0["result"] == g1["result"] == "PASS" else "FAIL",
            "evidence": "unit (captured API response + captured landing slice)",
        }
    return run_landing_fault(fault_id, dataset, clean_frame, definition, persistent_root)


def write_report(rows: list[dict], path: Path) -> None:
    headers = [
        "fault", "run_id", "manifest_path", "as_of_date", "injected_at", "detector",
        "detected_at", "channel", "received_at", "action", "gold_hash_before", "gold_hash_after",
        "result", "evidence",
    ]
    lines = [
        "# Week 9 local fault matrix",
        "",
        "This report uses captured fixtures and local WAP files only. No alert was sent and no BigQuery dataset was accessed.",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(key, "")).replace("|", "\\|") for key in headers) + " |")
    counts = {
        value: sum(str(row["result"]).startswith(value) for row in rows)
        for value in ("PASS", "FAIL", "UNVERIFIED")
    }
    lines.extend(["", f"Counts: {json.dumps(counts, sort_keys=True)}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--fault", choices=list(load_manifest()["faults"]))
    selector.add_argument("--all", action="store_true")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--root", type=Path, help="preserve one local WAP scenario for review/release")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)
    try:
        from dataforge.dq.results import require_isolated_dataset

        require_isolated_dataset(args.dataset)
        if args.root is not None and args.all:
            raise ValueError("--root supports one --fault at a time")
        manifest = load_manifest()
        clean_frame = pd.read_parquet(CAPTURE_PATH)
        fault_ids = list(manifest["faults"]) if args.all else [args.fault]
        rows = [
            run_fault(
                item,
                args.dataset,
                manifest,
                clean_frame,
                persistent_root=args.root,
            )
            for item in fault_ids
        ]
        write_report(rows, args.report)
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    counts = {
        label: sum(str(row["result"]).startswith(label) for row in rows)
        for label in ("PASS", "FAIL", "UNVERIFIED")
    }
    print(
        json.dumps(
            {
                "report": str(args.report),
                "counts": counts,
                "runs": [
                    {
                        "fault": row["fault"],
                        "run_id": row.get("run_id"),
                        "as_of_date": row.get("as_of_date"),
                        "manifest_path": row.get("manifest_path"),
                    }
                    for row in rows
                ],
            },
            sort_keys=True,
        )
    )
    return 1 if counts["FAIL"] or counts["UNVERIFIED"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
