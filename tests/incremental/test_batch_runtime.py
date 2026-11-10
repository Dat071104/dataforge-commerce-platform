from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from cloud.jobs.week5.consumer import make_run_id, process_manifest, stage_table_id
from dataforge.cloud.adapters import StoredObject
from dataforge.cloud.google_cloud import CloudAdapterError, GoogleCloudBackend
from dataforge.incremental.batch import (
    EVENT_KEYS,
    BatchValidationError,
    extract_batch,
    make_batch_id,
    normalize_event,
    row_value_sha256,
)
from dataforge.incremental.bronze import (
    EVENT_ARROW_SCHEMA,
    BronzeArtifactError,
    InjectedUploadFailure,
    download_verified_batch,
    serialize_batch,
    upload_batch,
    validate_parquet_bytes,
)


class FakeObjectStore:
    def __init__(self) -> None:
        self.latest: dict[tuple[str, str], int] = {}
        self.versions: dict[tuple[str, str, int], StoredObject] = {}
        self.put_calls: list[tuple[str, str, int]] = []
        self.lose_next_response = False
        self.next_generation = 100

    def get_object(self, bucket: str, name: str) -> StoredObject | None:
        generation = self.latest.get((bucket, name))
        if generation is None:
            return None
        return self.versions[(bucket, name, generation)]

    def get_object_generation(self, bucket: str, name: str, generation: int) -> StoredObject:
        try:
            return self.versions[(bucket, name, generation)]
        except KeyError as exc:
            raise FileNotFoundError(f"{bucket}/{name}#{generation}") from exc

    def put_object(
        self,
        bucket: str,
        name: str,
        payload: bytes,
        metadata: dict[str, str],
        content_type: str,
        *,
        if_generation_match: int,
    ) -> None:
        self.put_calls.append((bucket, name, if_generation_match))
        if if_generation_match != 0 or (bucket, name) in self.latest:
            raise RuntimeError("precondition failed")
        generation = self.next_generation
        self.next_generation += 1
        value = StoredObject(
            generation=generation,
            size_bytes=len(payload),
            crc32c="fake-crc32c",
            metadata=dict(metadata),
            payload=bytes(payload),
        )
        self.versions[(bucket, name, generation)] = value
        self.latest[(bucket, name)] = generation
        if self.lose_next_response:
            self.lose_next_response = False
            raise TimeoutError("simulated lost upload response")


def _event(
    seq: int,
    *,
    table: str = "orders",
    operation: str = "I",
    change_id: str | None = None,
    source_time: str = "2026-10-03T12:13:14.123456Z",
    business_time: str | None = None,
    payload_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if table == "orders":
        payload: dict[str, Any] = {
            "order_id": f"W5O{seq:04d}",
            "customer_id": "W5C0001",
            "order_date": "2026-10-01",
            "province_id": "VN-HN",
            "status": "delivered",
            "order_net_amount": "125000.00",
        }
        key = "order_id"
    else:
        payload = {
            "payment_id": f"W5P{seq:04d}",
            "order_id": "W5O0001",
            "payment_date": "2026-10-02",
            "amount": "125000.00",
            "status": "success",
            "method": "bank_transfer",
        }
        key = "payment_id"
    if business_time is None:
        business_time = (
            "2026-10-01T00:00:00.000000Z"
            if table == "orders"
            else "2026-10-02T00:00:00.000000Z"
        )
    if operation == "D":
        payload = {key: payload[key]}
    if payload_override is not None:
        payload = payload_override
    canonical_payload = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return {
        "change_seq": seq,
        "change_id": change_id or f"change-{seq}",
        "source_table": table,
        "business_key": payload[key],
        "operation": operation,
        "source_updated_at": source_time,
        "business_event_at": business_time,
        "schema_version": 1,
        "payload": canonical_payload,
        "payload_sha256": hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest(),
    }


def _batch(*events: dict[str, Any]):
    return extract_batch(events, from_seq=min(e["change_seq"] for e in events), to_seq=max(e["change_seq"] for e in events))


def test_event_digest_uses_documented_canonical_object_lines_and_batch_id_formula():
    first = _event(2, source_time="2026-10-03T12:13:14.123456+00:00")
    second = _event(1, table="payment_events")
    normalized = [normalize_event(second), normalize_event(first)]
    canonical_lines = []
    for event in normalized:
        wire_event = {
            key: event[key] if key in {"change_seq", "schema_version"} else str(event[key])
            for key in EVENT_KEYS
        }
        canonical_lines.append(
            json.dumps(
                wire_event,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    expected_digest = hashlib.sha256("\n".join(canonical_lines).encode("utf-8")).hexdigest()

    assert row_value_sha256([first, second]) == expected_digest
    assert row_value_sha256([second, first]) == expected_digest
    batch_id = make_batch_id("dataforge-operational-v1", 1, 2, expected_digest)
    expected_batch_id = hashlib.sha256(
        f"dataforge-operational-v1|1|2|{expected_digest}".encode("utf-8")
    ).hexdigest()
    assert batch_id == expected_batch_id


def test_extractor_supports_checkpoint_ranges_and_bounded_backfill():
    events = [_event(3), _event(1), _event(2)]

    normal = extract_batch(events, checkpoint=1, max_events=1, captured_upper_seq=3)
    backfill = extract_batch(events, from_seq=1, to_seq=2, max_events=2)

    assert normal is not None
    assert (normal.lower_seq, normal.upper_seq) == (2, 2)
    assert [event["change_seq"] for event in normal.events] == [2]
    assert backfill is not None
    assert (backfill.lower_seq, backfill.upper_seq) == (1, 2)
    assert [event["change_seq"] for event in backfill.events] == [1, 2]
    with pytest.raises(BatchValidationError, match="exceeds max_events"):
        extract_batch(events, from_seq=1, to_seq=3, max_events=2)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda value: value.update(schema_version=2), "schema_version"),
        (lambda value: value.update(source_updated_at="2026-10-03T12:00:00"), "UTC timezone"),
        (lambda value: value.update(payload_sha256="0" * 64), "payload_sha256"),
        (lambda value: value.update(extra="not documented"), "event keys"),
    ],
)
def test_event_validation_fails_closed(mutate, message):
    event = _event(1)
    mutate(event)

    with pytest.raises(BatchValidationError, match=message):
        normalize_event(event)


def test_delete_event_requires_explicit_key_only_payload():
    event = _event(7, operation="D")
    normalized = normalize_event(event)
    assert json.loads(normalized["payload"]) == {"order_id": "W5O0007"}

    event["payload"] = json.dumps(
        {"order_id": "W5O0007", "status": "cancelled"}, separators=(",", ":")
    )
    event["payload_sha256"] = hashlib.sha256(event["payload"].encode()).hexdigest()
    with pytest.raises(BatchValidationError, match="payload keys"):
        normalize_event(event)


def test_canonical_payload_text_rejects_duplicate_keys_and_noncanonical_whitespace():
    duplicate = _event(1)
    duplicate["payload"] = duplicate["payload"].replace('"order_id":', '"order_id":"ignored", "order_id":', 1)
    with pytest.raises(BatchValidationError, match="duplicate JSON object key"):
        normalize_event(duplicate)

    spaced = _event(1)
    spaced["payload"] = json.dumps(json.loads(spaced["payload"]), sort_keys=True, indent=2)
    with pytest.raises(BatchValidationError, match="canonical compact sorted JSON"):
        normalize_event(spaced)


def test_parquet_schema_is_typed_and_serialization_is_deterministic():
    batch = _batch(_event(1), _event(2, table="payment_events"))
    first = serialize_batch(batch)
    second = serialize_batch(batch)
    table = pq.read_table(io.BytesIO(first))

    assert first == second
    assert table.schema.equals(EVENT_ARROW_SCHEMA, check_metadata=True)
    assert table.schema.field("change_seq").type == pa.int64()
    assert table.schema.field("source_updated_at").type == pa.timestamp("us", tz="UTC")
    assert table.schema.field("schema_version").type == pa.string()


def test_create_only_bronze_and_complete_manifest_are_idempotent(tmp_path):
    batch = _batch(_event(1), _event(2, table="payment_events"))
    store = FakeObjectStore()
    store.lose_next_response = True

    first = upload_batch(batch, store, bucket="demo-bucket")
    put_count = len(store.put_calls)
    second = upload_batch(batch, store, bucket="demo-bucket")
    manifest_object = store.get_object_generation(
        "demo-bucket", first.manifest_name, first.manifest_generation
    )
    manifest = json.loads(manifest_object.payload)
    verified, verified_manifest, manifest_sha, parquet_bytes = download_verified_batch(
        store,
        manifest_uri=first.manifest_uri,
        manifest_generation=first.manifest_generation,
    )

    assert first.object_generation == second.object_generation
    assert first.manifest_generation == second.manifest_generation
    assert len(store.put_calls) == put_count
    assert all(precondition == 0 for _, _, precondition in store.put_calls)
    assert manifest["status"] == "COMPLETE"
    assert manifest["parquet"]["generation"] == first.object_generation
    assert verified.batch_id == batch.batch_id
    assert verified_manifest["batch_id"] == batch.batch_id
    assert manifest_sha == first.manifest_sha256
    assert hashlib.sha256(parquet_bytes).hexdigest() == first.parquet_sha256
    assert manifest["source_run_id"] == f"{batch.source_identity}:{batch.batch_id}"
    assert manifest["primary_key_columns"] == ["change_seq"]
    assert manifest["unique_change_id"] is True


def test_after_upload_failure_leaves_no_complete_manifest_and_retry_reuses_object():
    batch = _batch(_event(1))
    store = FakeObjectStore()
    with pytest.raises(InjectedUploadFailure, match="INJECTED_AFTER_UPLOAD"):
        upload_batch(batch, store, bucket="demo-bucket", fail_after_upload=True)

    object_names = [name for (bucket, name) in store.latest if bucket == "demo-bucket"]
    assert len(object_names) == 1
    assert object_names[0].startswith("bronze/week5/")
    assert not any("manifests/week5/" in name for name in object_names)
    object_generation = store.latest[("demo-bucket", object_names[0])]

    receipt = upload_batch(batch, store, bucket="demo-bucket")
    assert receipt.object_generation == object_generation
    assert receipt.manifest_generation > 0
    assert receipt.batch_id == batch.batch_id


def test_explicit_range_allows_sequence_gaps_and_records_actual_event_min_max():
    batch = extract_batch([_event(1), _event(3)], from_seq=1, to_seq=4, max_events=4)
    store = FakeObjectStore()

    receipt = upload_batch(batch, store, bucket="demo-bucket")
    manifest_object = store.get_object_generation(
        "demo-bucket", receipt.manifest_name, receipt.manifest_generation
    )
    manifest = json.loads(manifest_object.payload)
    verified, _, _, _ = download_verified_batch(
        store,
        manifest_uri=receipt.manifest_uri,
        manifest_generation=receipt.manifest_generation,
    )

    assert (batch.lower_seq, batch.upper_seq) == (1, 4)
    assert (manifest["event_seq_min"], manifest["event_seq_max"]) == (1, 3)
    assert [event["change_seq"] for event in verified.events] == [1, 3]


def test_consumer_fetches_exact_generations_stages_local_verified_bytes_and_publishes(tmp_path):
    batch = _batch(_event(1), _event(2, table="payment_events"))
    store = ConsumerFakeBackend()
    bronze = upload_batch(batch, store, bucket="demo-bucket")
    store.uri = bronze.manifest_uri
    store.generation = bronze.manifest_generation
    sql_path = tmp_path / "publish.sql"
    sql_path.write_text("SELECT @batch_id, {{STAGING_TABLE_ID}}", encoding="utf-8")

    result = process_manifest(
        manifest_uri=bronze.manifest_uri,
        manifest_generation=bronze.manifest_generation,
        run_mode="normal",
        project_id="dataforge-demo-123",
        region="us-central1",
        backend=store,
        execution_id="week5-execution-1",
        attempt=0,
        fail_after_merge_once=True,
        sql_path=sql_path,
    )

    assert result.status == "PUBLISHED"
    assert result.batch_id == batch.batch_id
    assert result.stage_table_id == f"dataforge-demo-123.staging.week5_events_{batch.batch_id[:16]}"
    assert result.stage_load_job_id == "load-job"
    assert result.publish_job_id.startswith("week5_publish_")
    assert store.staged_bytes == serialize_batch(batch)
    assert store.publish_parameters["run_mode"] == "normal"
    assert store.publish_parameters["fail_after_merge_once"] is True
    assert store.publish_parameters["source_run_id"] == f"{batch.source_identity}:{batch.batch_id}"
    assert store.publish_parameters["published_check_job_id"] == store.published_check["job_id"]
    assert store.publish_sql.count("{{STAGING_TABLE_ID}}") == 0
    assert [event["status"] for event in store.run_events] == [
        "DISCOVERED", "VALIDATED", "STAGED"
    ]


def test_consumer_rejects_manifest_outside_the_approved_bucket_prefix(tmp_path):
    batch = _batch(_event(1))
    store = ConsumerFakeBackend()
    bronze = upload_batch(batch, store, bucket="demo-bucket")
    sql_path = tmp_path / "publish.sql"
    sql_path.write_text("SELECT @batch_id, {{STAGING_TABLE_ID}}", encoding="utf-8")

    with pytest.raises(CloudAdapterError, match="approved Week-5 Bronze prefix"):
        process_manifest(
            manifest_uri=bronze.manifest_uri,
            manifest_generation=bronze.manifest_generation,
            run_mode="normal",
            project_id="dataforge-demo-123",
            region="us-central1",
            expected_bucket="approved-bucket",
            backend=store,
            execution_id="week5-wrong-bucket",
            sql_path=sql_path,
        )

    assert store.stage_calls == 0
    assert store.publish_calls == 0
    assert len(store.failure_records) == 1


def test_consumer_failure_after_stage_is_recorded_and_does_not_publish(tmp_path):
    batch = _batch(_event(1))
    store = ConsumerFakeBackend()
    bronze = upload_batch(batch, store, bucket="demo-bucket")
    sql_path = tmp_path / "publish.sql"
    sql_path.write_text("SELECT @batch_id, {{STAGING_TABLE_ID}}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="INJECTED_AFTER_STAGE"):
        process_manifest(
            manifest_uri=bronze.manifest_uri,
            manifest_generation=bronze.manifest_generation,
            run_mode="normal",
            project_id="dataforge-demo-123",
            region="us-central1",
            backend=store,
            execution_id="week5-after-stage",
            fail_at="after_stage",
            sql_path=sql_path,
        )

    assert store.stage_calls == 1
    assert store.publish_calls == 0
    assert [event["status"] for event in store.run_events] == [
        "DISCOVERED", "VALIDATED", "STAGED"
    ]
    assert store.failure_records[0]["error_code"] == "INJECTED_FAILURE"


def test_runtime_storage_create_negative_probe_requires_and_records_http_403(tmp_path, monkeypatch):
    class Forbidden(Exception):
        code = 403

    batch = _batch(_event(1))
    store = ConsumerFakeBackend()
    bronze = upload_batch(batch, store, bucket="demo-bucket")
    sql_path = tmp_path / "publish.sql"
    sql_path.write_text("SELECT @batch_id, {{STAGING_TABLE_ID}}", encoding="utf-8")

    def deny_create(*args, **kwargs):
        raise Forbidden("expected IAM denial")

    monkeypatch.setattr(store, "put_object", deny_create)
    result = process_manifest(
        manifest_uri=bronze.manifest_uri,
        manifest_generation=bronze.manifest_generation,
        run_mode="normal",
        project_id="dataforge-demo-123",
        region="us-central1",
        expected_bucket="demo-bucket",
        backend=store,
        execution_id="week5-iam-negative",
        probe_storage_create_denied=True,
        sql_path=sql_path,
    )

    assert result.status == "PUBLISHED"
    assert result.runtime_iam_create_denied is True
    assert any(event["status"] == "IAM_NEGATIVE_PASS" for event in store.run_events)
    assert not any("iam-negative" in name for bucket, name in store.latest if bucket == "demo-bucket")


def test_published_replay_is_no_op_without_recreating_expired_staging(tmp_path):
    batch = _batch(_event(1))
    store = ConsumerFakeBackend()
    bronze = upload_batch(batch, store, bucket="demo-bucket")
    sql_path = tmp_path / "publish.sql"
    sql_path.write_text("SELECT @batch_id, {{STAGING_TABLE_ID}}", encoding="utf-8")
    store.published = True

    result = process_manifest(
        manifest_uri=bronze.manifest_uri,
        manifest_generation=bronze.manifest_generation,
        run_mode="backfill",
        project_id="dataforge-demo-123",
        region="us-central1",
        backend=store,
        execution_id="week5-replay-1",
        sql_path=sql_path,
    )

    assert result.status == "NO_OP"
    assert result.stage_load_job_id == ""
    assert result.publish_job_id == ""
    assert store.stage_calls == 0
    assert store.publish_calls == 0
    assert store.published_check["expected_metadata"]["row_value_sha256"] == batch.row_value_sha256


def test_consumer_records_only_sanitized_failure_event_after_runtime_error(tmp_path):
    batch = _batch(_event(1))
    store = ConsumerFakeBackend()
    bronze = upload_batch(batch, store, bucket="demo-bucket")
    sql_path = tmp_path / "publish.sql"
    sql_path.write_text("SELECT @batch_id, {{STAGING_TABLE_ID}}", encoding="utf-8")
    store.stage_error = RuntimeError("credential=must-not-enter-ledger")

    with pytest.raises(RuntimeError, match="must-not-enter-ledger"):
        process_manifest(
            manifest_uri=bronze.manifest_uri,
            manifest_generation=bronze.manifest_generation,
            run_mode="normal",
            project_id="dataforge-demo-123",
            region="us-central1",
            backend=store,
            execution_id="week5-failing-execution",
            sql_path=sql_path,
        )

    assert len(store.failure_records) == 1
    record = store.failure_records[0]
    assert record["run_id"] == make_run_id("week5-failing-execution", 0)
    assert record["error_code"] == "WEEK5_PROCESSING_FAILED"
    assert "credential" not in record["error_message"]
    assert record["error_message"] == (
        "Week-5 processing failed; inspect bounded Cloud Run and BigQuery job records."
    )


def test_failure_ledger_insert_uses_deterministic_event_id_and_is_idempotent():
    class Job:
        def __init__(self, job_id, rows=()):
            self.job_id = job_id
            self._rows = list(rows)

        def result(self, **kwargs):
            return iter(self._rows)

    class BQModule:
        @staticmethod
        def QueryJobConfig(**kwargs):
            return kwargs

        @staticmethod
        def ScalarQueryParameter(name, kind, value):
            return name, kind, value

    class QueryClient:
        def __init__(self):
            self.calls = []
            self.jobs = [Job("check-1"), Job("insert-1"), Job("check-2", [{"status": "FAILED"}])]

        def query(self, sql, **kwargs):
            self.calls.append((sql, kwargs))
            return self.jobs.pop(0)

    backend = GoogleCloudBackend.__new__(GoogleCloudBackend)
    backend._bigquery_module = BQModule
    backend._bigquery = QueryClient()
    backend._request_retry = None

    first = backend.record_week5_failure(
        project_id="dataforge-demo-123",
        region="us-central1",
        run_id="a" * 32,
        error_code="BATCH_VALIDATION_FAILED",
        error_message="Sanitized failure.",
    )
    second = backend.record_week5_failure(
        project_id="dataforge-demo-123",
        region="us-central1",
        run_id="a" * 32,
        error_code="BATCH_VALIDATION_FAILED",
        error_message="Sanitized failure.",
    )

    assert first["recorded"] is True
    assert second["recorded"] is False
    assert second["existing_status"] == "FAILED"
    assert len(backend._bigquery.calls) == 3
    insert_sql, insert_kwargs = backend._bigquery.calls[1]
    assert "(event_id, run_id, execution_id, batch_id, status" in insert_sql
    assert "@error_code" in insert_sql and "@error_message" in insert_sql
    assert "FROM UNNEST([1]) AS seed WHERE NOT EXISTS" in insert_sql
    parameters = insert_kwargs["job_config"]["query_parameters"]
    assert ("event_id", "STRING", f"{'a' * 32}:FAILED") in parameters
    assert "NOT EXISTS" in insert_sql


def test_parquet_checksum_and_payload_validation_fail_closed():
    batch = _batch(_event(1))
    store = FakeObjectStore()
    receipt = upload_batch(batch, store, bucket="demo-bucket")
    manifest_object = store.get_object_generation(
        "demo-bucket", receipt.manifest_name, receipt.manifest_generation
    )
    manifest = json.loads(manifest_object.payload)
    stored_parquet = store.get_object_generation(
        "demo-bucket", receipt.object_name, receipt.object_generation
    )
    tampered = bytes([stored_parquet.payload[0] ^ 1]) + stored_parquet.payload[1:]
    with pytest.raises(BronzeArtifactError, match="SHA-256 mismatch"):
        validate_parquet_bytes(
            tampered,
            manifest=manifest,
            manifest_bucket="demo-bucket",
            store=store,
        )

    table = pq.read_table(io.BytesIO(stored_parquet.payload))
    column_index = table.column_names.index("schema_version")
    altered = table.set_column(column_index, table.schema.field("schema_version"), pa.array(["2"]))
    buffer = io.BytesIO()
    pq.write_table(altered, buffer, compression="zstd", use_dictionary=False, version="2.6")
    malformed_bytes = buffer.getvalue()
    malformed_sha = hashlib.sha256(malformed_bytes).hexdigest()
    malformed_manifest = json.loads(json.dumps(manifest))
    malformed_manifest["parquet"]["sha256"] = malformed_sha
    malformed_manifest["parquet"]["size_bytes"] = len(malformed_bytes)
    altered_name = (
        f"bronze/week5/source=dataforge-operational-v1/sha256={malformed_sha}/part-000.parquet"
    )
    malformed_manifest["parquet"]["object_name"] = altered_name
    store.versions[("demo-bucket", altered_name, receipt.object_generation)] = replace(
        stored_parquet,
        size_bytes=len(malformed_bytes),
        metadata={
            **stored_parquet.metadata,
            "dataforge-week5-sha256": malformed_sha,
        },
        payload=malformed_bytes,
    )
    with pytest.raises(BronzeArtifactError, match="payload or schema version"):
        validate_parquet_bytes(
            malformed_bytes,
            manifest=malformed_manifest,
            manifest_bucket="demo-bucket",
            store=store,
        )


def test_gcs_generation_reader_does_not_follow_latest_generation():
    batch = _batch(_event(1))
    store = FakeObjectStore()
    receipt = upload_batch(batch, store, bucket="demo-bucket")
    original = store.get_object_generation("demo-bucket", receipt.object_name, receipt.object_generation)
    latest_generation = store.next_generation
    store.next_generation += 1
    store.versions[("demo-bucket", receipt.object_name, latest_generation)] = StoredObject(
        generation=latest_generation,
        size_bytes=1,
        crc32c="bad",
        metadata={},
        payload=b"x",
    )
    store.latest[("demo-bucket", receipt.object_name)] = latest_generation

    assert store.get_object_generation(
        "demo-bucket", receipt.object_name, receipt.object_generation
    ).payload == original.payload
    assert store.get_object("demo-bucket", receipt.object_name).payload == b"x"


def test_cloud_run_and_local_token_auth_factories_are_explicit_and_guarded(monkeypatch):
    seen: dict[str, Any] = {}

    def fake_initialize(self, project_id, credentials, *, clients_factory=None):
        self.credentials = credentials
        self.project_id = project_id

    monkeypatch.setattr(GoogleCloudBackend, "_initialize_clients", fake_initialize)
    backend = GoogleCloudBackend.from_local_access_token(
        "dataforge-demo-123",
        "one-off-token",
        credentials_factory=lambda token, project: (seen.update(token=token, project=project) or "local-creds"),
    )
    assert backend.credentials == "local-creds"
    assert seen == {"token": "one-off-token", "project": "dataforge-demo-123"}

    monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
    monkeypatch.delenv("CLOUD_RUN_EXECUTION", raising=False)
    with pytest.raises(CloudAdapterError, match="only in a Cloud Run Job"):
        GoogleCloudBackend.from_cloud_run_metadata("dataforge-demo-123", credentials_factory=lambda _: "creds")

    monkeypatch.setenv("CLOUD_RUN_JOB", "job")
    monkeypatch.setenv("CLOUD_RUN_EXECUTION", "execution")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "C:/developer/adc.json")
    with pytest.raises(CloudAdapterError, match="must not be overridden"):
        GoogleCloudBackend.from_cloud_run_metadata("dataforge-demo-123", credentials_factory=lambda _: "creds")


def test_run_and_stage_identifiers_are_bounded():
    assert len(make_run_id("valid-execution", 1)) == 32
    with pytest.raises(ValueError, match="single-retry"):
        make_run_id("valid-execution", 2)
    with pytest.raises(ValueError, match="batch ID"):
        stage_table_id("dataforge-demo-123", "not-a-hash")


class ConsumerFakeBackend(FakeObjectStore):
    def __init__(self) -> None:
        super().__init__()
        self.published = False
        self.published_check: dict[str, Any] = {}
        self.stage_calls = 0
        self.publish_calls = 0
        self.staged_bytes: bytes | None = None
        self.publish_parameters: dict[str, Any] = {}
        self.publish_sql = ""
        self.failure_records: list[dict[str, Any]] = []
        self.run_events: list[dict[str, Any]] = []
        self.stage_error: Exception | None = None

    def is_week5_batch_published(self, **kwargs):
        self.published_check = kwargs
        return {
            "published": self.published,
            "job_id": kwargs["job_id"],
            "bytes_processed": 512,
            "bytes_billed": 0,
            "maximum_bytes_billed": kwargs["maximum_bytes_billed"],
        }

    def stage_week5_events(self, **kwargs):
        self.stage_calls += 1
        if self.stage_error is not None:
            raise self.stage_error
        self.staged_bytes = kwargs["parquet_bytes"]
        return {
            "load_job_id": "load-job",
            "verify_job_id": "verify-job",
            "row_value_sha256": kwargs["row_value_sha256"],
        }

    def run_week5_publish(self, **kwargs):
        self.publish_calls += 1
        self.publish_parameters = dict(kwargs["parameters"])
        self.publish_sql = kwargs["sql"].replace(
            "{{STAGING_TABLE_ID}}", f"`{kwargs['staging_table_id']}`"
        )
        assert kwargs["staging_table_id"] in self.publish_sql
        assert kwargs["job_id"].startswith("week5_publish_")
        return {
            "job_id": kwargs["job_id"],
            "publication_status": "PUBLISHED",
            "bytes_processed": 1024,
            "bytes_billed": 0,
            "maximum_bytes_billed": kwargs["maximum_bytes_billed"],
        }

    def record_week5_failure(self, **kwargs):
        self.failure_records.append(dict(kwargs))
        return {"recorded": True, "existing_status": "FAILED"}

    def record_week5_run_event(self, **kwargs):
        self.run_events.append(dict(kwargs))
        return {"status": kwargs["status"], "job_id": f"ledger-{kwargs['status']}"}
