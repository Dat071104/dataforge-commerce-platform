from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from faults.cases import mutate_landing_frame

from dataforge.dq.gate import run_landing_gate
from dataforge.dq.results import MemoryResultSink
from dataforge.dq.wap import (
    initialize_published,
    release_quarantine,
    write_audit_publish,
)

CAPTURE = Path(__file__).parent / "faults" / "weather_7date_slice.parquet"
AS_OF = date.today()


@pytest.fixture
def clean_frame():
    return pd.read_parquet(CAPTURE)


def gated(frame, sink):
    return run_landing_gate(
        frame,
        dataset="w9_drill",
        observation_date=AS_OF,
        enforce="block",
        result_sink=sink,
    )


def test_p1_quarantine_preserves_published_gold_hash(tmp_path, clean_frame):
    root = tmp_path / "w9_drill"
    before = initialize_published(root, clean_frame)
    sink = MemoryResultSink()
    frame = mutate_landing_frame("F01", clean_frame)
    report = gated(frame, sink)
    result = write_audit_publish(root, "fault-f01", frame, report, result_sink=sink)
    manifest = root / "quarantine" / "fault-f01" / "manifest.json"

    assert result["action"] == "BLOCK"
    assert result["gold_sha256_before"] == before
    assert result["gold_sha256_after"] == before
    assert "G1.LANDING.PROVINCE_ID_NOT_NULL" in result["failed_check_ids"]
    assert manifest.is_file()
    assert (root / "quarantine" / "fault-f01" / "candidate.parquet").is_file()


def test_quarantine_release_requires_repair_and_reason(tmp_path, clean_frame):
    root = tmp_path / "w9_drill"
    before = initialize_published(root, clean_frame)
    invalid = mutate_landing_frame("F01", clean_frame)
    report = gated(invalid, MemoryResultSink())
    write_audit_publish(root, "fault-f01", invalid, report)

    blocked = release_quarantine(
        root,
        "fault-f01",
        AS_OF,
        release_reason="retry after review",
        result_sink=MemoryResultSink(),
    )
    assert blocked["action"] == "BLOCK"
    assert blocked["gold_sha256_before"] == before
    assert blocked["gold_sha256_after"] == before

    candidate_path = root / "quarantine" / "fault-f01" / "candidate.parquet"
    repaired = pd.read_parquet(candidate_path)
    repaired.loc[repaired.index[0], "province_id"] = clean_frame.loc[0, "province_id"]
    repaired.to_parquet(candidate_path, index=False)
    released = release_quarantine(
        root,
        "fault-f01",
        AS_OF,
        release_reason="corrected province_id and passed a fresh gate",
        result_sink=MemoryResultSink(),
    )
    assert released["action"] == "RELEASE"
    assert released["status"] == "RELEASED"
    assert released["gold_sha256_after"] == before


def test_additive_schema_warning_publishes(tmp_path, clean_frame):
    root = tmp_path / "w9_drill"
    initialize_published(root, clean_frame)
    candidate = mutate_landing_frame("F05b", clean_frame)
    sink = MemoryResultSink()
    report = gated(candidate, sink)
    result = write_audit_publish(root, "fault-f05b", candidate, report, result_sink=sink)

    assert report.blocked is False
    assert result["action"] == "PUBLISH"
    assert result["status"] == "PUBLISHED"


def test_replay_is_noop_and_emits_no_p1_p2_result(tmp_path, clean_frame):
    root = tmp_path / "w9_drill"
    before = initialize_published(root, clean_frame)
    sink = MemoryResultSink()
    report = gated(clean_frame, sink)
    result = write_audit_publish(root, "fault-f09", clean_frame, report, result_sink=sink)

    replay_rows = [
        row for row in sink.results if row.check_id == "G1.LANDING.IDEMPOTENCY_REPLAY"
    ]
    assert result["action"] == "NO_OP"
    assert result["gold_sha256_before"] == before
    assert result["gold_sha256_after"] == before
    assert len(replay_rows) == 1
    assert replay_rows[0].severity == "None"
    assert replay_rows[0].status == "NOOP"


def test_clean_negative_control_has_zero_failed_p1_p2_rows(tmp_path, clean_frame):
    root = tmp_path / "w9_drill"
    initialize_published(root, clean_frame)
    sink = MemoryResultSink()
    report = gated(clean_frame, sink)
    result = write_audit_publish(root, "fault-fn0", clean_frame, report, result_sink=sink)

    failures = [
        row for row in sink.results if row.severity in {"P1", "P2"} and row.status != "PASS"
    ]
    assert not failures
    assert result["action"] == "NO_OP"
