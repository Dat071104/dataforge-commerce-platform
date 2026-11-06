"""Manifest promotion and Bronze artifact integrity regression tests."""
import hashlib
import json
from pathlib import Path

import pytest


def _ingest_paths(monkeypatch, tmp_path):
    from dataforge import ingestion
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=300, seed=42, dest=source)
    bronze = tmp_path / "bronze"
    manifests = tmp_path / "manifests"
    monkeypatch.setattr(ingestion, "BRONZE", bronze)
    monkeypatch.setattr(ingestion, "MANIFESTS", manifests)
    return ingestion, source, bronze, manifests


def _active_run(manifests):
    pointer = json.loads((manifests / "active.json").read_text(encoding="utf-8"))
    run_path = manifests / "runs" / f"{pointer['run_id']}.json"
    return pointer, run_path, json.loads(run_path.read_text(encoding="utf-8"))


def test_ingest_records_and_reuses_actual_parquet_sha256(monkeypatch, tmp_path):
    ingestion, source, _, manifests = _ingest_paths(monkeypatch, tmp_path)

    first = ingestion.ingest(source)
    _, _, run = _active_run(manifests)
    for name, metadata in run["sources"].items():
        parquet_path = Path(metadata["bronze_file"])
        digest = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        assert metadata["bronze_sha256"] == digest
        assert metadata["rows_accepted"] == first[name]["rows_accepted"]

    second = ingestion.ingest(source)
    assert all(
        first[name]["bronze_sha256"] == second[name]["bronze_sha256"]
        for name in first
    )


def test_first_subset_ingest_is_recorded_but_not_loadable_as_a_complete_snapshot(
    monkeypatch, tmp_path
):
    from dataforge import database
    from dataforge.ingestion import contracts

    ingestion, source, _, manifests = _ingest_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(database, "MANIFESTS", manifests)

    ingestion.ingest(source, sources=["geography"])

    _, _, run = _active_run(manifests)
    assert run["status"] == "complete"
    assert set(run["sources"]) == {"geography"}
    with pytest.raises(ValueError, match="incomplete sources"):
        database._source_manifests(contracts())


def test_legacy_manifests_fail_closed_until_full_ingest_migration(monkeypatch, tmp_path):
    from dataforge import database
    from dataforge.ingestion import contracts

    ingestion, source, _, manifests = _ingest_paths(monkeypatch, tmp_path)
    ingestion.ingest(source)
    _, run_path, run = _active_run(manifests)
    for metadata in run["sources"].values():
        metadata.pop("bronze_sha256")
    run_path.write_text(json.dumps(run), encoding="utf-8")

    ingestion.ingest(source, sources=["orders"])
    monkeypatch.setattr(database, "MANIFESTS", manifests)
    _, _, subset_run = _active_run(manifests)
    assert subset_run["sources"]["orders"].get("bronze_sha256")
    assert not subset_run["sources"]["geography"].get("bronze_sha256")

    with pytest.raises(ValueError, match="legacy format without a valid bronze_sha256"):
        database._source_manifests(contracts())

    migrated = ingestion.ingest(source)
    _, _, new_run = _active_run(manifests)
    assert all(entry.get("bronze_sha256") for entry in new_run["sources"].values())
    assert all(entry.get("bronze_sha256") for entry in migrated.values())


def test_database_load_rejects_legacy_checksum_manifest_before_connection(monkeypatch, tmp_path):
    from dataforge import database

    ingestion, source, _, manifests = _ingest_paths(monkeypatch, tmp_path)
    ingestion.ingest(source)
    monkeypatch.setattr(database, "MANIFESTS", manifests)
    pointer, run_path, run = _active_run(manifests)
    run["sources"]["orders"].pop("bronze_sha256")
    run_path.write_text(json.dumps(run), encoding="utf-8")
    database_connection_attempted = False

    def unexpected_connection():
        nonlocal database_connection_attempted
        database_connection_attempted = True
        raise AssertionError("legacy manifest validation must precede database access")

    monkeypatch.setattr(database, "database_url", unexpected_connection)
    with pytest.raises(ValueError, match="legacy format without a valid bronze_sha256"):
        database.load()

    assert not database_connection_attempted
    assert _active_run(manifests)[0] == pointer


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("schema", "bronze schema mismatch for orders"),
        ("rows", "bronze row count mismatch for orders"),
    ],
)
def test_database_manifest_preflight_rejects_schema_and_row_count_mismatch(
    monkeypatch, tmp_path, mutation, expected_error
):
    import pandas as pd

    from dataforge import database
    from dataforge.ingestion import contracts

    ingestion, source, _, manifests = _ingest_paths(monkeypatch, tmp_path)
    ingestion.ingest(source)
    monkeypatch.setattr(database, "MANIFESTS", manifests)
    _, run_path, run = _active_run(manifests)
    order_metadata = run["sources"]["orders"]
    parquet_path = Path(order_metadata["bronze_file"])

    if mutation == "schema":
        frame = pd.read_parquet(parquet_path).rename(columns={"order_id": "unexpected_id"})
        frame.to_parquet(parquet_path, engine="pyarrow", index=False)
        order_metadata["bronze_sha256"] = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    else:
        order_metadata["rows_accepted"] += 1
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_error):
        database._source_manifests(contracts())


def test_external_weather_ingest_requires_consistent_csv_marker_and_sidecar(
    monkeypatch, tmp_path
):
    import pandas as pd

    from dataforge.weather import PROVENANCE_DIR

    ingestion, source, _, manifests = _ingest_paths(monkeypatch, tmp_path)
    ingestion.ingest(source)
    old_pointer = (manifests / "active.json").read_bytes()

    weather_path = source / "weather_daily.csv"
    old_sha = hashlib.sha256(weather_path.read_bytes()).hexdigest()
    frame = pd.read_csv(weather_path, dtype="string")
    frame.loc[0, "source"] = "open_meteo_era5"
    frame.to_csv(weather_path, index=False)
    new_sha = hashlib.sha256(weather_path.read_bytes()).hexdigest()

    marker_path = source / "_DATAFORGE_SOURCE.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["source_overrides"]["weather_daily"] = "open_meteo_era5"
    marker["file_sha256"]["weather_daily"] = new_sha
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    sidecar_dir = source / PROVENANCE_DIR
    sidecar_dir.mkdir(parents=True)
    sidecar_path = sidecar_dir / "weather_provenance.json"
    sidecar_path.write_text(
        json.dumps({
            "status": "complete",
            "weather_csv_sha256": old_sha,
            "weather_csv_rows": len(frame),
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="do not describe the same complete snapshot"):
        ingestion.ingest(source)

    assert (manifests / "active.json").read_bytes() == old_pointer


def test_external_weather_ingest_accepts_matching_complete_provenance(
    monkeypatch, tmp_path
):
    import pandas as pd

    from dataforge.weather import PROVENANCE_DIR

    ingestion, source, _, manifests = _ingest_paths(monkeypatch, tmp_path)
    weather_path = source / "weather_daily.csv"
    frame = pd.read_csv(weather_path, dtype="string")
    frame.loc[0, "source"] = "open_meteo_era5"
    frame.to_csv(weather_path, index=False)
    weather_sha = hashlib.sha256(weather_path.read_bytes()).hexdigest()
    marker_path = source / "_DATAFORGE_SOURCE.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["source_overrides"]["weather_daily"] = "open_meteo_era5"
    marker["file_sha256"]["weather_daily"] = weather_sha
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    sidecar_dir = source / PROVENANCE_DIR
    sidecar_dir.mkdir()
    (sidecar_dir / "weather_provenance.json").write_text(
        json.dumps({
            "status": "complete",
            "weather_csv_sha256": weather_sha,
            "weather_csv_rows": len(frame),
        }),
        encoding="utf-8",
    )

    results = ingestion.ingest(source)
    assert results["weather_daily"]["data_classification"] == "open_meteo_era5"
    assert _active_run(manifests)[2]["sources"]["weather_daily"]["bronze_sha256"]


def test_failed_source_validation_keeps_prior_active_pointer(monkeypatch, tmp_path):
    ingestion, source, _, manifests = _ingest_paths(monkeypatch, tmp_path)
    ingestion.ingest(source)
    old_pointer = (manifests / "active.json").read_bytes()
    old_run_id = _active_run(manifests)[0]["run_id"]
    previous_validate = ingestion.validate

    def fail_on_second_source(frame, name):
        if name == "products":
            raise ValueError("injected validation failure")
        return previous_validate(frame, name)

    monkeypatch.setattr(ingestion, "validate", fail_on_second_source)
    with pytest.raises(ValueError, match="injected validation failure"):
        ingestion.ingest(source, sources=["geography", "products"])

    assert (manifests / "active.json").read_bytes() == old_pointer
    assert _active_run(manifests)[0]["run_id"] == old_run_id


def test_active_pointer_write_failure_keeps_previous_complete_run(monkeypatch, tmp_path):
    ingestion, source, _, manifests = _ingest_paths(monkeypatch, tmp_path)
    ingestion.ingest(source)
    old_pointer = (manifests / "active.json").read_bytes()
    old_run_id = _active_run(manifests)[0]["run_id"]
    atomic_write = ingestion._write_json_atomically

    def fail_pointer(path, value):
        if path.name == "active.json":
            raise OSError("injected pointer promotion failure")
        atomic_write(path, value)

    monkeypatch.setattr(ingestion, "_write_json_atomically", fail_pointer)
    with pytest.raises(OSError, match="injected pointer promotion failure"):
        ingestion.ingest(source, sources=["products"])

    assert (manifests / "active.json").read_bytes() == old_pointer
    assert _active_run(manifests)[0]["run_id"] == old_run_id
    failed = []
    for path in (manifests / "runs").glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") == "failed":
            failed.append(record)
    assert len(failed) == 1
