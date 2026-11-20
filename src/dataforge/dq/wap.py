"""Local Write-Audit-Publish and quarantine harness for isolated drill files."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from .gate import run_landing_gate
from .results import MemoryResultSink, make_result, require_isolated_dataset

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid4().hex}.stage")
    try:
        staged.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with staged.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _frame_bytes(frame) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    frame.to_parquet(buffer, index=False)
    return buffer.getvalue()


def initialize_published(root: Path, clean_frame) -> str:
    """Create the local last-good Gold snapshot once for a drill scenario."""
    require_isolated_dataset(root.name)
    target = root / "published" / "weather_landing.parquet"
    if target.exists():
        raise FileExistsError("published snapshot already exists; refusing to reset a drill root")
    payload = _frame_bytes(clean_frame)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return _sha256_bytes(payload)


def write_audit_publish(
    root: Path,
    run_id: str,
    candidate_frame,
    gate_report,
    *,
    result_sink=None,
) -> dict:
    """Stage and audit a batch; quarantine blocking failures without changing Gold."""
    require_isolated_dataset(root.name)
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must contain only letters, digits, underscore, or hyphen")
    payload = _frame_bytes(candidate_frame)
    digest = _sha256_bytes(payload)
    batch_dir = root / "batches" / run_id
    candidate_path = batch_dir / "candidate.parquet"
    if batch_dir.exists():
        raise FileExistsError("batch run_id already exists; use a new run_id")
    batch_dir.mkdir(parents=True, exist_ok=False)
    candidate_path.write_bytes(payload)
    published_path = root / "published" / "weather_landing.parquet"
    before_hash = _sha256_file(published_path)
    failed_p1 = [
        result.check_id
        for result in gate_report.results
        if result.severity == "P1" and result.status == "FAIL"
    ]
    base_manifest = {
        "run_id": run_id,
        "created_at_utc": _utc_now(),
        "candidate_sha256": digest,
        "gate_run_id": gate_report.run_id,
        "dataset": root.name,
        "gate_layer": gate_report.layer,
        "enforcement": gate_report.enforce,
    }

    if gate_report.blocked:
        quarantine_dir = root / "quarantine" / run_id
        quarantine_dir.mkdir(parents=True, exist_ok=False)
        quarantine_candidate = quarantine_dir / "candidate.parquet"
        os.replace(candidate_path, quarantine_candidate)
        after_hash = _sha256_file(published_path)
        if before_hash != after_hash:
            raise AssertionError("P1 quarantine changed the published Gold hash")
        manifest = {
            **base_manifest,
            "status": "QUARANTINED",
            "reason": ";".join(failed_p1) or "blocking gate failure",
            "failed_check_ids": failed_p1,
            "gold_sha256_before": before_hash,
            "gold_sha256_after": after_hash,
        }
        _write_json_atomic(quarantine_dir / "manifest.json", manifest)
        return {"action": "BLOCK", **manifest}

    if before_hash is not None and before_hash == digest:
        if result_sink is not None:
            result_sink.write(
                [
                    make_result(
                        run_id=gate_report.run_id,
                        check_id="G1.LANDING.IDEMPOTENCY_REPLAY",
                        layer="G1",
                        severity="None",
                        status="NOOP",
                        observed={
                            "candidate_sha256": digest,
                            "published_hash_matches": True,
                            "dataset": root.name,
                            "date": gate_report.observation_date,
                        },
                        threshold="same request content does not append or republish",
                        failing_rows=0,
                        contract_version="1.0.0",
                    )
                ]
            )
        manifest = {
            **base_manifest,
            "status": "NOOP",
            "check_id": "G1.LANDING.IDEMPOTENCY_REPLAY",
            "reason": "candidate hash matches the published snapshot",
            "gold_sha256_before": before_hash,
            "gold_sha256_after": before_hash,
        }
        _write_json_atomic(root / "manifests" / f"{run_id}.json", manifest)
        return {"action": "NO_OP", **manifest}

    published_path.parent.mkdir(parents=True, exist_ok=True)
    staged = published_path.with_name(f".{published_path.name}.{uuid4().hex}.stage")
    try:
        staged.write_bytes(payload)
        with staged.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(staged, published_path)
    finally:
        staged.unlink(missing_ok=True)
    after_hash = _sha256_file(published_path)
    manifest = {
        **base_manifest,
        "status": "PUBLISHED",
        "reason": None,
        "failed_check_ids": [],
        "gold_sha256_before": before_hash,
        "gold_sha256_after": after_hash,
    }
    _write_json_atomic(root / "manifests" / f"{run_id}.json", manifest)
    return {"action": "PUBLISH", **manifest}


def release_quarantine(
    root: Path,
    run_id: str,
    observation_date: date,
    *,
    release_reason: str,
    result_sink=None,
) -> dict:
    """Deliberately re-audit and release a corrected local quarantined batch."""
    require_isolated_dataset(root.name)
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must contain only letters, digits, underscore, or hyphen")
    if not release_reason.strip():
        raise ValueError("a release reason is required")
    quarantine_dir = root / "quarantine" / run_id
    manifest_path = quarantine_dir / "manifest.json"
    candidate_path = quarantine_dir / "candidate.parquet"
    if not manifest_path.is_file() or not candidate_path.is_file():
        raise FileNotFoundError("quarantined run and manifest must both exist")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "QUARANTINED":
        raise ValueError("only a quarantined run may be released")

    import pandas as pd

    frame = pd.read_parquet(candidate_path)
    sink = result_sink or MemoryResultSink()
    report = run_landing_gate(
        frame,
        dataset=root.name,
        observation_date=observation_date,
        enforce="block",
        result_sink=sink,
    )
    if report.blocked:
        return {
            "action": "BLOCK",
            "status": "QUARANTINED",
            "failed_check_ids": [
                result.check_id
                for result in report.results
                if result.severity == "P1" and result.status == "FAIL"
            ],
            "gold_sha256_before": _sha256_file(root / "published" / "weather_landing.parquet"),
            "gold_sha256_after": _sha256_file(root / "published" / "weather_landing.parquet"),
        }

    published_path = root / "published" / "weather_landing.parquet"
    before_hash = _sha256_file(published_path)
    payload = candidate_path.read_bytes()
    digest = _sha256_bytes(payload)
    staged = published_path.with_name(f".{published_path.name}.{uuid4().hex}.stage")
    try:
        staged.write_bytes(payload)
        with staged.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(staged, published_path)
    finally:
        staged.unlink(missing_ok=True)
    after_hash = _sha256_file(published_path)
    released = {
        **manifest,
        "status": "RELEASED",
        "release_reason": release_reason.strip(),
        "released_at_utc": _utc_now(),
        "candidate_sha256": digest,
        "release_gate_run_id": report.run_id,
        "gold_sha256_before": before_hash,
        "gold_sha256_after": after_hash,
    }
    _write_json_atomic(manifest_path, released)
    return {"action": "RELEASE", **released}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    release = subparsers.add_parser("release", help="re-audit and release one local quarantine")
    release.add_argument("--root", type=Path, required=True)
    release.add_argument("--run-id", required=True)
    release.add_argument("--date", required=True, dest="observation_date")
    release.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        parsed_date = date.fromisoformat(args.observation_date)
        if parsed_date.isoformat() != args.observation_date:
            raise ValueError("date must use canonical YYYY-MM-DD")
        result = release_quarantine(
            args.root,
            args.run_id,
            parsed_date,
            release_reason=args.reason,
        )
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 1 if result["action"] == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
