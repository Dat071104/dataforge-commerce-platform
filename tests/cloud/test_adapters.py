from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dataforge.cloud.adapters import (
    BigQueryLoadReceipt,
    CloudAdapterError,
    DataIntegrityError,
    DuplicateObjectError,
    LocationMismatchError,
    ManifestError,
    PermissionDeniedError,
    ProjectMismatchError,
    StoredObject,
    load_validated_snapshot,
    preflight_snapshot,
    raw_value_rows_sha256,
    value_rows_sha256,
)
from dataforge.cloud.adapters import transfer_snapshot as _transfer_snapshot_impl
from dataforge.cloud.contracts import SOURCE_CONTRACTS, FieldContract
from dataforge.cloud.google_cloud import _typed_insert_sql

RUN_ID = "a" * 32
INGEST_RUN_ID = "b" * 32


def transfer_snapshot(snapshot, backend, **kwargs):
    kwargs.setdefault("expected_project_number", "123456")
    return _transfer_snapshot_impl(snapshot, backend, **kwargs)


def _parquet_bytes(source: str) -> bytes:
    contract = SOURCE_CONTRACTS[source]
    string_fields = [field.name for field in contract.fields]
    values: dict[str, list[str]] = {}
    for field in contract.fields:
        if field.name in contract.primary_key and field.bq_type == "STRING":
            values[field.name] = [f"{source}-one", f"{source}-two"]
        elif field.bq_type == "DATE":
            values[field.name] = ["2026-01-01", "2026-01-02"]
        elif field.bq_type == "INT64":
            values[field.name] = ["1", "2"]
        elif field.bq_type == "NUMERIC":
            scale = field.scale or 0
            values[field.name] = [
                f"1.{''.join(['0'] * scale)}" if scale else "1",
                f"2.{''.join(['0'] * scale)}" if scale else "2",
            ]
        else:
            values[field.name] = ["sample", "sample"]
    table = pa.table({name: pa.array(values[name], type=pa.string()) for name in string_fields})
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="snappy")
    return buffer.getvalue()


def _write_complete_run(tmp_path: Path) -> tuple[Path, Path, dict[str, dict]]:
    bronze_root = tmp_path / "bronze"
    manifest_dir = tmp_path / "manifests"
    (manifest_dir / "runs").mkdir(parents=True)
    sources: dict[str, dict] = {}
    for source in SOURCE_CONTRACTS:
        source_sha = hashlib.sha256(f"source:{source}".encode()).hexdigest()
        payload = _parquet_bytes(source)
        parquet_sha = hashlib.sha256(payload).hexdigest()
        parquet_path = bronze_root / source / f"sha256={source_sha}" / "part-000.parquet"
        parquet_path.parent.mkdir(parents=True)
        parquet_path.write_bytes(payload)
        sources[source] = {
            "source": source,
            "source_file": f"local-only/{source}.csv",
            "source_sha256": source_sha,
            "bronze_file": str(parquet_path),
            "bronze_sha256": parquet_sha,
            "rows_accepted": 2,
            "rows_rejected": 0,
            "data_classification": "synthetic",
            "ingest_run_id": INGEST_RUN_ID,
        }

    run = {
        "run_id": RUN_ID,
        "status": "complete",
        "sources": sources,
    }
    (manifest_dir / "active.json").write_text(json.dumps({"run_id": RUN_ID}), encoding="utf-8")
    (manifest_dir / "runs" / f"{RUN_ID}.json").write_text(json.dumps(run), encoding="utf-8")
    return manifest_dir, bronze_root, sources


class FakeBackend:
    def __init__(self, *, bucket_location: str = "us-central1", dataset_location: str = "us-central1"):
        self.bucket_location = bucket_location
        self.dataset_location = dataset_location
        self.bucket_project_number = "123456"
        self.objects: dict[tuple[str, str], StoredObject] = {}
        self.put_calls: list[tuple[str, str, int]] = []
        self.load_calls = 0
        self.load_invocations = 0
        self.put_error: str | None = None
        self.value_mismatch = False
        self.raw_value_mismatch = False
        self.loaded_tables: dict[tuple[str, str], tuple[tuple, BigQueryLoadReceipt]] = {}

    def target_locations(
        self,
        project_id: str,
        bucket: str,
        dataset: str,
        expected_project_number: str,
    ) -> tuple[str, str]:
        if expected_project_number != self.bucket_project_number:
            raise ProjectMismatchError("bucket is owned by a different project")
        return self.bucket_location, self.dataset_location

    def get_object(self, bucket: str, name: str) -> StoredObject | None:
        return self.objects.get((bucket, name))

    def put_object(self, bucket, name, payload, metadata, content_type, *, if_generation_match):
        self.put_calls.append((bucket, name, if_generation_match))
        if if_generation_match != 0:
            raise AssertionError("the adapter must use create-only generation preconditions")
        key = (bucket, name)
        if key in self.objects:
            raise RuntimeError("precondition conflict")
        generation = 100 + len(self.objects)
        stored_payload = payload
        if self.put_error == "partial" and name.startswith("bronze/"):
            stored_payload = payload[: max(1, len(payload) // 2)]
        self.objects[key] = StoredObject(
            generation=generation,
            size_bytes=len(stored_payload),
            crc32c="fake-crc32c",
            metadata=dict(metadata),
            payload=stored_payload,
        )
        if self.put_error == "lost-response" and name.startswith("bronze/"):
            self.put_error = None
            raise TimeoutError("upload committed but response was lost")
        if self.put_error == "partial" and name.startswith("bronze/"):
            self.put_error = None
            raise TimeoutError("interrupted upload")

    def load_typed_parquet(self, **kwargs) -> BigQueryLoadReceipt:
        self.load_invocations += 1
        contract = kwargs["contract"]
        signature = (
            kwargs["source_sha256"],
            kwargs["parquet_sha256"],
            kwargs["gcs_generation"],
            kwargs["expected_rows"],
            kwargs["raw_value_sha256"],
            kwargs["source_value_sha256"],
        )
        key = (kwargs["source"], kwargs["run_id"])
        if key in self.loaded_tables:
            prior_signature, receipt = self.loaded_tables[key]
            if prior_signature != signature:
                raise DataIntegrityError("existing fake staging table source differs")
            return replace(receipt, load_reused=True, cast_reused=True)
        self.load_calls += 1
        value_sha256 = kwargs["source_value_sha256"]
        receipt = BigQueryLoadReceipt(
            raw_table=f"{kwargs['source']}_raw_{kwargs['run_id']}",
            typed_table=f"{kwargs['source']}_{kwargs['run_id']}",
            load_job_id=f"load-{kwargs['run_id']}",
            cast_job_id=f"cast-{kwargs['run_id']}",
            metrics_job_id=f"metrics-{kwargs['run_id']}",
            row_count=kwargs["row_count"],
            filtered_row_count=1,
            null_counts=kwargs["expected_null_counts"],
            schema=contract.fields,
            raw_reconciliation_job_id=f"raw-reconcile-{kwargs['run_id']}",
            raw_value_sha256=(
                "0" * 64 if self.raw_value_mismatch else kwargs["raw_value_sha256"]
            ),
            raw_values_match=not self.raw_value_mismatch,
            reconciliation_job_id=f"reconcile-{kwargs['run_id']}",
            source_value_sha256=value_sha256,
            bigquery_value_sha256="0" * 64 if self.value_mismatch else value_sha256,
            exact_values_match=not self.value_mismatch,
        )
        self.loaded_tables[key] = (signature, receipt)
        return receipt


def _snapshot(tmp_path: Path, source: str = "orders"):
    manifest_dir, bronze_root, _ = _write_complete_run(tmp_path)
    return load_validated_snapshot(source, manifest_dir=manifest_dir, bronze_root=bronze_root)


def test_load_validated_snapshot_checks_active_manifest_hash_rows_and_schema(tmp_path):
    snapshot = _snapshot(tmp_path, "orders")

    assert snapshot.active_run_id == RUN_ID
    assert snapshot.source_ingest_run_id == INGEST_RUN_ID
    assert snapshot.row_count == 2
    assert snapshot.parquet_sha256 == hashlib.sha256(snapshot.parquet_bytes).hexdigest()
    assert snapshot.parquet_schema == (
        "order_id:string",
        "customer_id:string",
        "order_date:string",
        "province_id:string",
        "status:string",
    )
    assert snapshot.filter_field == "order_id"
    assert snapshot.expected_filter_rows == 1


def test_preflight_is_network_free_and_marks_live_checks_unverified(tmp_path):
    snapshot = _snapshot(tmp_path, "geography")

    result = preflight_snapshot(
        snapshot,
        project_id="demo-project-123",
        bucket="dataforge-demo-123456",
        region="us-central1",
        bucket_location="US-CENTRAL1",
        dataset_location="us-central1",
    )

    assert result["status"] == "LOCAL_PREFLIGHT_PASS"
    assert result["network_used"] is False
    assert result["credentials_checked"] is False
    assert result["resource_mutation"] is False
    assert result["region_check"] == "DECLARED_MATCH_NOT_LIVE_VERIFIED"
    assert result["typed_schema"][0]["bq_type"] == "STRING"


def test_bad_parquet_hash_fails_closed(tmp_path):
    manifest_dir, bronze_root, sources = _write_complete_run(tmp_path)
    parquet = Path(sources["orders"]["bronze_file"])
    parquet.write_bytes(parquet.read_bytes() + b"tampered")

    with pytest.raises(DataIntegrityError, match="SHA-256 mismatch"):
        load_validated_snapshot("orders", manifest_dir=manifest_dir, bronze_root=bronze_root)


def test_wrong_parquet_schema_fails_even_when_manifest_digest_matches(tmp_path):
    manifest_dir, bronze_root, sources = _write_complete_run(tmp_path)
    metadata = sources["orders"]
    parquet = Path(metadata["bronze_file"])
    table = pq.read_table(parquet).select(list(reversed(SOURCE_CONTRACTS["orders"].columns)))
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    payload = buffer.getvalue()
    parquet.write_bytes(payload)
    metadata["bronze_sha256"] = hashlib.sha256(payload).hexdigest()
    run_path = manifest_dir / "runs" / f"{RUN_ID}.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["sources"]["orders"] = metadata
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(DataIntegrityError, match="schema mismatch"):
        load_validated_snapshot("orders", manifest_dir=manifest_dir, bronze_root=bronze_root)


def test_wrong_row_count_fails_closed(tmp_path):
    manifest_dir, bronze_root, sources = _write_complete_run(tmp_path)
    sources["orders"]["rows_accepted"] = 3
    run_path = manifest_dir / "runs" / f"{RUN_ID}.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["sources"]["orders"]["rows_accepted"] = 3
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(DataIntegrityError, match="row-count mismatch"):
        load_validated_snapshot("orders", manifest_dir=manifest_dir, bronze_root=bronze_root)


def test_duplicate_primary_keys_fail_even_when_manifest_hash_matches(tmp_path):
    manifest_dir, bronze_root, sources = _write_complete_run(tmp_path)
    metadata = sources["geography"]
    parquet = Path(metadata["bronze_file"])
    table = pq.read_table(io.BytesIO(parquet.read_bytes()))
    index = table.column_names.index("province_id")
    table = table.set_column(
        index,
        table.schema.field(index),
        pa.array(["same-key", "same-key"], type=pa.string()),
    )
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    payload = buffer.getvalue()
    parquet.write_bytes(payload)
    run_path = manifest_dir / "runs" / f"{RUN_ID}.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["sources"]["geography"]["bronze_sha256"] = hashlib.sha256(payload).hexdigest()
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(DataIntegrityError, match="duplicate primary key"):
        load_validated_snapshot("geography", manifest_dir=manifest_dir, bronze_root=bronze_root)


def test_blank_nullable_fields_are_expected_as_bigquery_nulls(tmp_path):
    manifest_dir, bronze_root, sources = _write_complete_run(tmp_path)
    metadata = sources["shipments"]
    parquet = Path(metadata["bronze_file"])
    table = pq.read_table(io.BytesIO(parquet.read_bytes()))
    index = table.column_names.index("delivery_date")
    table = table.set_column(index, table.schema.field(index), pa.array(["", "sample"]))
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    payload = buffer.getvalue()
    parquet.write_bytes(payload)
    metadata["bronze_sha256"] = hashlib.sha256(payload).hexdigest()
    run_path = manifest_dir / "runs" / f"{RUN_ID}.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["sources"]["shipments"] = metadata
    run_path.write_text(json.dumps(run), encoding="utf-8")

    snapshot = load_validated_snapshot(
        "shipments", manifest_dir=manifest_dir, bronze_root=bronze_root
    )

    assert snapshot.expected_null_counts == {"delivery_date": 1}


def test_incomplete_active_snapshot_is_rejected(tmp_path):
    manifest_dir, bronze_root, _ = _write_complete_run(tmp_path)
    run_path = manifest_dir / "runs" / f"{RUN_ID}.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["sources"].pop("weather_daily")
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(ManifestError, match="complete configured source set"):
        load_validated_snapshot("orders", manifest_dir=manifest_dir, bronze_root=bronze_root)


def test_wrong_region_stops_before_any_upload_or_bigquery_call(tmp_path):
    snapshot = _snapshot(tmp_path)
    backend = FakeBackend(bucket_location="asia-southeast1", dataset_location="us-central1")

    with pytest.raises(LocationMismatchError):
        transfer_snapshot(
            snapshot, backend, project_id="demo-project-123", bucket="dataforge-demo-123456"
        )

    assert not backend.put_calls
    assert backend.load_calls == 0


def test_bucket_owned_by_different_project_stops_before_any_upload(tmp_path):
    snapshot = _snapshot(tmp_path)
    backend = FakeBackend()
    backend.bucket_project_number = "999999"

    with pytest.raises(ProjectMismatchError, match="different project"):
        transfer_snapshot(
            snapshot,
            backend,
            project_id="demo-project-123",
            expected_project_number="123456",
            bucket="dataforge-demo-123456",
        )

    assert backend.put_calls == []
    assert backend.load_calls == 0


def test_unauthorized_identity_is_reported_without_bigquery_load(tmp_path):
    snapshot = _snapshot(tmp_path)
    backend = FakeBackend()
    backend.put_error = "denied"
    backend.put_object = lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("403"))

    with pytest.raises(PermissionDeniedError):
        transfer_snapshot(
            snapshot, backend, project_id="demo-project-123", bucket="dataforge-demo-123456"
        )

    assert backend.load_calls == 0


def test_existing_duplicate_object_with_different_bytes_is_never_overwritten(tmp_path):
    snapshot = _snapshot(tmp_path)
    backend = FakeBackend()
    object_name = (
        f"bronze/source={snapshot.source}/sha256={snapshot.parquet_sha256}/part-000.parquet"
    )
    backend.objects[("dataforge-demo-123456", object_name)] = StoredObject(
        generation=9,
        size_bytes=4,
        crc32c="fake-crc32c",
        metadata={"dataforge-sha256": "0" * 64},
        payload=b"evil",
    )

    with pytest.raises(DuplicateObjectError):
        transfer_snapshot(
            snapshot, backend, project_id="demo-project-123", bucket="dataforge-demo-123456"
        )

    assert backend.put_calls == []
    assert backend.load_calls == 0


def test_partial_upload_bytes_fail_closed_before_manifest_or_bigquery(tmp_path):
    snapshot = _snapshot(tmp_path)
    backend = FakeBackend()
    backend.put_error = "partial"

    with pytest.raises(DataIntegrityError):
        transfer_snapshot(
            snapshot, backend, project_id="demo-project-123", bucket="dataforge-demo-123456"
        )

    assert len(backend.objects) == 1
    assert backend.load_calls == 0
    assert not any("manifests/" in name for _, name in backend.objects)


def test_retry_after_lost_upload_response_reuses_verified_generation(tmp_path):
    snapshot = _snapshot(tmp_path, "geography")
    backend = FakeBackend()
    backend.put_error = "lost-response"

    receipt = transfer_snapshot(
        snapshot, backend, project_id="demo-project-123", bucket="dataforge-demo-123456"
    )

    assert receipt.gcs_generation > 0
    assert receipt.gcs_size_bytes == len(snapshot.parquet_bytes)
    assert receipt.gcs_crc32c
    assert receipt.row_count == snapshot.row_count
    assert receipt.bigquery.filtered_row_count == snapshot.expected_filter_rows
    assert backend.load_calls == 1
    # Both data and manifest were created with generation-match zero.
    assert all(precondition == 0 for _, _, precondition in backend.put_calls)
    manifest_name = (
        f"manifests/source={snapshot.source}/active_run={snapshot.active_run_id}/manifest.json"
    )
    manifest = backend.get_object("dataforge-demo-123456", manifest_name)
    assert manifest is not None
    assert receipt.manifest_generation == manifest.generation
    assert receipt.manifest_size_bytes == manifest.size_bytes
    assert receipt.manifest_crc32c == manifest.crc32c
    assert receipt.manifest_sha256 == hashlib.sha256(manifest.payload).hexdigest()


def test_repeated_identical_object_is_verified_and_not_rewritten(tmp_path):
    snapshot = _snapshot(tmp_path, "geography")
    backend = FakeBackend()
    first = transfer_snapshot(
        snapshot, backend, project_id="demo-project-123", bucket="dataforge-demo-123456"
    )
    original_put_count = len(backend.put_calls)
    second = transfer_snapshot(
        snapshot, backend, project_id="demo-project-123", bucket="dataforge-demo-123456"
    )

    assert first.target_project_number == "123456"
    assert second.gcs_generation == first.gcs_generation
    assert second.manifest_generation == first.manifest_generation
    assert len(backend.put_calls) == original_put_count
    assert first.bigquery.load_reused is False
    assert second.bigquery.load_reused is True
    assert second.bigquery.cast_reused is True
    assert backend.load_calls == 1
    assert backend.load_invocations == 2


def test_bigquery_value_digest_mismatch_fails_closed(tmp_path):
    snapshot = _snapshot(tmp_path, "geography")
    backend = FakeBackend()
    backend.value_mismatch = True

    with pytest.raises(DataIntegrityError, match="row values"):
        transfer_snapshot(
            snapshot, backend, project_id="demo-project-123", bucket="dataforge-demo-123456"
        )


def test_bigquery_raw_value_digest_mismatch_fails_closed(tmp_path):
    snapshot = _snapshot(tmp_path, "geography")
    backend = FakeBackend()
    backend.raw_value_mismatch = True

    with pytest.raises(DataIntegrityError, match="raw row values"):
        transfer_snapshot(
            snapshot, backend, project_id="demo-project-123", bucket="dataforge-demo-123456"
        )


def test_value_digest_is_order_independent_and_preserves_numeric_scale():
    contract = SOURCE_CONTRACTS["order_items"]
    rows = (
        ("item-2", "order-1", "p-1", "3", "12.50", "0.1250"),
        ("item-1", "order-1", "p-2", "1", "9.99", "0.0000"),
    )

    assert value_rows_sha256(rows, contract) == value_rows_sha256(tuple(reversed(rows)), contract)


def test_raw_digest_distinguishes_blank_string_from_null():
    from dataforge.cloud.contracts import source_contract

    contract = source_contract("shipments")
    blank = (("ship-1", "order-1", "2026-01-01", "", "delivered", "carrier"),)
    null = (("ship-1", "order-1", "2026-01-01", None, "delivered", "carrier"),)

    assert raw_value_rows_sha256(blank, contract) != raw_value_rows_sha256(null, contract)
    assert value_rows_sha256(blank, contract) == value_rows_sha256(null, contract)


def test_google_backend_scopes_adc_quota_to_explicit_project(monkeypatch, tmp_path):
    google_auth = pytest.importorskip("google.auth")
    credentials_module = pytest.importorskip("google.auth.credentials")
    from dataforge.cloud.google_cloud import GoogleCloudBackend

    credentials = credentials_module.AnonymousCredentials()
    root = tmp_path / "isolated" / "dataforge-gcloud"
    root.mkdir(parents=True)
    credential_file = root / "application_default_credentials.json"
    observed: dict[str, str] = {}

    def fake_load_credentials_from_file(
        filename: str, *, quota_project_id: str
    ):
        observed["filename"] = filename
        observed["quota_project_id"] = quota_project_id
        return credentials, None

    monkeypatch.setenv("CLOUDSDK_CONFIG", str(root))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(credential_file))
    monkeypatch.setattr(
        google_auth, "load_credentials_from_file", fake_load_credentials_from_file
    )
    backend = GoogleCloudBackend("demo-project-123")

    assert observed == {
        "filename": str(credential_file.resolve()),
        "quota_project_id": "demo-project-123",
    }
    assert backend._storage._credentials is credentials
    assert backend._bigquery._credentials is credentials


def test_google_backend_rejects_credentials_outside_isolated_sdk_root(
    monkeypatch, tmp_path
):
    from dataforge.cloud.google_cloud import GoogleCloudBackend

    root = tmp_path / "gcloud-dataforge"
    root.mkdir()
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(root))
    monkeypatch.setenv(
        "GOOGLE_APPLICATION_CREDENTIALS", str(tmp_path / "global-adc.json")
    )

    with pytest.raises(CloudAdapterError, match="inside the isolated"):
        GoogleCloudBackend("demo-project-123")


def test_google_backend_requires_isolated_sdk_root(monkeypatch):
    from dataforge.cloud.google_cloud import GoogleCloudBackend

    monkeypatch.delenv("CLOUDSDK_CONFIG", raising=False)

    with pytest.raises(CloudAdapterError, match="CLOUDSDK_CONFIG"):
        GoogleCloudBackend("demo-project-123")


def test_google_backend_requires_explicit_adc_inside_isolated_root(monkeypatch):
    from dataforge.cloud.google_cloud import GoogleCloudBackend

    monkeypatch.setenv("CLOUDSDK_CONFIG", "C:/isolated/dataforge-gcloud")
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    with pytest.raises(CloudAdapterError, match="GOOGLE_APPLICATION_CREDENTIALS"):
        GoogleCloudBackend("demo-project-123")


def test_typed_schema_preserves_exact_numeric_precision_and_avoids_float(tmp_path):
    snapshot = _snapshot(tmp_path, "order_items")
    schema = snapshot.contract.fields
    by_name = {field.name: field for field in schema}

    assert by_name["quantity"].bq_type == "INT64"
    assert by_name["unit_price"] == FieldContract("unit_price", "NUMERIC", False, 18, 2)
    assert by_name["discount_pct"] == FieldContract("discount_pct", "NUMERIC", False, 8, 4)
    assert all(field.bq_type != "FLOAT64" for field in schema)


def test_nullable_fields_cast_empty_strings_to_null_and_values_are_parameterized():
    from dataforge.cloud.contracts import source_contract

    contract = source_contract("shipments")
    sql = _typed_insert_sql(
        "demo-project-123.staging.shipments_raw_a",
        "demo-project-123.staging.shipments_a",
        contract,
    )

    assert "CAST(NULLIF(`delivery_date`, '') AS DATE)" in sql
    assert "CAST(`ship_date` AS DATE)" in sql
    assert "FLOAT64" not in sql
