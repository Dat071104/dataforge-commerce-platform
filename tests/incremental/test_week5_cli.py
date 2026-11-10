"""Offline CLI safety and wire integration checks for the Week-5 runner."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from dataforge.incremental import source
from scripts import week5_incremental as cli


def _sample_event() -> source.JournalEvent:
    payload = {
        "order_id": "W5O9001",
        "customer_id": "W5C9001",
        "order_date": "2026-10-01",
        "province_id": "VN-HN",
        "status": "delivered",
        "order_net_amount": "125000.00",
    }
    source_at = "2026-10-10T00:00:00.000000Z"
    business_at = "2026-10-01T00:00:00.000000Z"
    payload_sha = hashlib.sha256(source._canonical_json(payload).encode()).hexdigest()
    event_sha = source._event_digest(
        "orders", "W5O9001", "I", source_at, business_at, payload
    )
    return source.JournalEvent(
        1,
        source.SOURCE_IDENTITY,
        "cli-sample-order",
        "orders",
        "W5O9001",
        "I",
        source_at,
        business_at,
        1,
        payload,
        payload_sha,
        event_sha,
    )


def test_batch_defaults_to_local_dry_run_without_cloud_auth(monkeypatch, capsys):
    sample = _sample_event()
    monkeypatch.setattr(cli, "_target", lambda: dict(cli.APPROVED_TARGET))
    monkeypatch.setattr(
        cli.source,
        "read_normal_batch",
        lambda checkpoint, max_events: SimpleNamespace(
            events=(sample,), captured_upper_seq=1
        ),
    )
    monkeypatch.setattr(
        cli,
        "_backend",
        lambda target: (_ for _ in ()).throw(AssertionError("dry-run must not create cloud clients")),
    )
    monkeypatch.delenv("DATAFORGE_GCP_ACCESS_TOKEN", raising=False)

    args = cli.build_parser().parse_args(["batch", "--max-events", "1"])
    cli._cmd_batch(args)

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "DRY_RUN_READY"
    assert output["batch_id"] == source.batch_identity(1, 1, output["row_value_sha256"])
    assert output["event_count"] == 1
    assert output["checkpoint_mutated"] is False


def test_cli_schema_requires_explicit_execute_flag():
    args = cli.build_parser().parse_args(["schema"])
    try:
        cli._cmd_schema(args)
    except cli.Week5CliError as exc:
        assert "explicit --execute" in str(exc)
    else:
        raise AssertionError("schema command must not write without --execute")
