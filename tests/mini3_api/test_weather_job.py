from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from cloud.jobs.week7_weather.weather_job import (
    BRONZE_BUCKET,
    LANDING_FIELDS,
    LANDING_TABLE,
    MAXIMUM_BYTES_BILLED,
    PROJECT_ID,
    WeatherJobError,
    _canonical_json,
    _landing_merge_sql,
    _landing_reconciliation_sql,
    build_request_id,
    default_observation_date,
    ingest,
    land,
    validate_invocation_id,
    validate_observation_date,
    validate_provinces,
    verify,
)


class MemoryBlob:
    def __init__(self, bucket: "MemoryBucket", name: str, generation: int | None = None):
        self.bucket = bucket
        self.name = name
        self.generation = generation

    def upload_from_string(self, payload: bytes, **kwargs: Any) -> None:
        assert kwargs["if_generation_match"] == 0
        if self.name in self.bucket.objects:
            from google.api_core.exceptions import PreconditionFailed

            raise PreconditionFailed("object already exists")
        generation = self.bucket.next_generation
        self.bucket.next_generation += 1
        self.bucket.objects[self.name] = {generation: bytes(payload)}
        self.generation = generation

    def reload(self) -> None:
        versions = self.bucket.objects.get(self.name)
        if not versions:
            from google.api_core.exceptions import NotFound

            raise NotFound(self.name)
        if self.generation is None:
            self.generation = max(versions)
        elif self.generation not in versions:
            from google.api_core.exceptions import NotFound

            raise NotFound(self.name)

    def download_as_bytes(self) -> bytes:
        assert self.generation is not None
        return self.bucket.objects[self.name][self.generation]


class MemoryBucket:
    def __init__(self):
        self.objects: dict[str, dict[int, bytes]] = {}
        self.next_generation = 100

    def blob(self, name: str, generation: int | None = None) -> MemoryBlob:
        return MemoryBlob(self, name, generation)


class MemoryStorageClient:
    def __init__(self):
        self.target_bucket = MemoryBucket()

    def bucket(self, name: str) -> MemoryBucket:
        assert name == BRONZE_BUCKET
        return self.target_bucket


class FakeField:
    def __init__(self, name: str, field_type: str, required: bool):
        self.name = name
        self.field_type = field_type
        self.mode = "REQUIRED" if required else "NULLABLE"


class FakeTable:
    def __init__(self):
        self.schema = [FakeField(name, kind, not nullable) for name, kind, nullable in LANDING_FIELDS]
        self.time_partitioning = type("Partition", (), {"field": "observation_date"})()


class FakeQueryJob:
    def __init__(self, result: list[dict] | None = None, job_id: str = "job-test"):
        self._result = result or []
        self.job_id = job_id
        self.total_bytes_billed = 10
        self.num_dml_affected_rows = 3
        self.config = None
        self.query = None

    def result(self, timeout: int):
        assert timeout == 180
        return iter(self._result)


class FakeBigQueryClient:
    def __init__(self):
        self.jobs: list[FakeQueryJob] = []
        self.sql: list[str] = []
        self.configs: list[Any] = []

    def get_table(self, table_id: str):
        assert table_id == LANDING_TABLE
        return FakeTable()

    def query(self, sql: str, *, job_config: Any, location: str):
        assert location == "us-central1"
        self.sql.append(sql)
        self.configs.append(job_config)
        if sql.lstrip().startswith("MERGE"):
            job = FakeQueryJob(job_id="merge-job")
        else:
            job = FakeQueryJob(
                [
                    {
                        "expected_rows": 3,
                        "observed_rows": 3,
                        "matched_rows": 3,
                        "missing_rows": 0,
                        "unexpected_rows": 0,
                        "mismatched_rows": 0,
                    }
                ],
                job_id="reconcile-job",
            )
        job.config = job_config
        job.query = sql
        self.jobs.append(job)
        return job


def _fake_source_fetch(start: date, end: date, *, provinces: list[str], dest: Path) -> int:
    assert start == end
    values = {
        "HCM": (0.0, 33.7),
        "HN": (1.5, 28.25),
        "DN": (None, None),
    }
    with (dest / "weather_daily.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["province_id", "observation_date", "precipitation_mm", "temp_max_c", "source"]
        )
        for province in provinces:
            rain, temperature = values[province]
            writer.writerow(
                [province, start.isoformat(), "" if rain is None else rain,
                 "" if temperature is None else temperature, "open_meteo_era5"]
            )

    responses = []
    requested = []
    for province in provinces:
        latitude, longitude = {
            "HCM": (10.8231, 106.6297),
            "HN": (21.0285, 105.8542),
            "DN": (16.0544, 108.2022),
        }[province]
        rain, temperature = values[province]
        raw_payload = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "Asia/Ho_Chi_Minh",
            "daily": {
                "time": [start.isoformat()],
                "precipitation_sum": [rain],
                "temperature_2m_max": [temperature],
            },
        }
        raw_bytes = _canonical_json(raw_payload)
        digest = hashlib.sha256(raw_bytes).hexdigest()
        relative = Path(".open_meteo") / "responses" / province / f"sha256={digest}.json"
        raw_path = dest / relative
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw_bytes)
        responses.append(
            {
                "province_id": province,
                "attempt": 1,
                "http_status": 200,
                "response_sha256": digest,
                "hash_basis": "response_content",
                "raw_response_json": relative.as_posix(),
            }
        )
        requested.append(
            {"province_id": province, "latitude": latitude, "longitude": longitude}
        )
    provenance = {
        "status": "complete",
        "provider": "Open-Meteo",
        "endpoint": "https://archive-api.open-meteo.com/v1/archive",
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "requested_provinces": requested,
        "daily_fields": ["precipitation_sum", "temperature_2m_max"],
        "timezone": "Asia/Ho_Chi_Minh",
        "model": "era5",
        "responses": responses,
        "weather_csv_rows": len(provinces),
        "attribution": {
            "text": "Weather data from Open-Meteo Historical Weather API.",
            "provider_url": "https://open-meteo.com/",
            "api_documentation_url": "https://open-meteo.com/en/docs/historical-weather-api",
            "data_license": "CC BY 4.0",
            "license_url": "https://open-meteo.com/en/terms",
        },
    }
    provenance_path = dest / ".open_meteo" / "weather_provenance.json"
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    return len(provinces)


@pytest.fixture
def fixed_run_time() -> datetime:
    return datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def _ingest_fixture(storage: MemoryStorageClient, fixed_run_time: datetime, invocation: str = "test-run-001"):
    return ingest(
        observation_date="2026-11-05",
        provinces="HCM,HN,DN",
        invocation_id=invocation,
        now=fixed_run_time,
        storage_client=storage,
        source_fetch=_fake_source_fetch,
    )


def test_settling_lag_uses_hcm_calendar_day_and_rejects_too_recent_date(fixed_run_time):
    assert default_observation_date(fixed_run_time) == date(2026, 11, 5)
    assert validate_observation_date("2026-11-05", today=date(2026, 11, 12)) == date(2026, 11, 5)
    with pytest.raises(WeatherJobError, match="settled"):
        validate_observation_date("2026-11-06", today=date(2026, 11, 12))
    with pytest.raises(WeatherJobError, match="YYYY-MM-DD"):
        validate_observation_date("2026-11-5", today=date(2026, 11, 12))


def test_allowlist_rejects_duplicates_unknown_provinces_and_wide_requests():
    assert validate_provinces("HCM,HN,DN") == ["HCM", "HN", "DN"]
    for invalid in ("HCM,HCM", "HCM,SG", "HCM,HN,DN,HCM", ""):
        with pytest.raises(WeatherJobError):
            validate_provinces(invalid)


def test_request_id_is_stable_for_exact_responses_and_changes_on_revision():
    digests = {province: "a" * 64 for province in ("HCM", "HN", "DN")}
    first = build_request_id(
        observation_date=date(2026, 11, 5),
        provinces=["HCM", "HN", "DN"],
        response_sha256_by_province=digests,
    )
    same = build_request_id(
        observation_date=date(2026, 11, 5),
        provinces=["HCM", "HN", "DN"],
        response_sha256_by_province=dict(digests),
    )
    revised = build_request_id(
        observation_date=date(2026, 11, 5),
        provinces=["HCM", "HN", "DN"],
        response_sha256_by_province={**digests, "HN": "b" * 64},
    )
    assert len(first) == 64 and first == same and first != revised


def test_invocation_id_is_safe_for_a_deterministic_gcs_object_path():
    assert validate_invocation_id("scheduled-run_001") == "scheduled-run_001"
    for invalid in ("../bad", "has space", "x" * 65, ""):
        with pytest.raises(WeatherJobError):
            validate_invocation_id(invalid)


def test_ingest_publishes_exact_generation_manifest_and_invocation_receipt(fixed_run_time):
    storage = MemoryStorageClient()
    result = _ingest_fixture(storage, fixed_run_time)

    assert result["status"] == "COMPLETE"
    assert result["row_count"] == 3
    assert result["manifest_uri"].startswith(
        f"gs://{BRONZE_BUCKET}/weather_mini3/v1/manifests/observation_date=2026-11-05/"
    )
    assert len(result["request_id"]) == 64
    assert result["manifest_generation"] > 0
    assert result["execution_receipt_generation"] > 0
    names = list(storage.target_bucket.objects)
    assert len([name for name in names if "/raw/" in name]) == 3
    assert len([name for name in names if name.endswith("weather_daily.parquet")]) == 1
    assert len([name for name in names if "/manifests/" in name]) == 1
    receipt_object = next(name for name in names if "/executions/" in name)
    receipt = json.loads(storage.target_bucket.objects[receipt_object][
        result["execution_receipt_generation"]
    ])
    assert receipt["status"] == "COMPLETE"
    assert receipt["request_id"] == result["request_id"]
    assert receipt["manifest_generation"] == result["manifest_generation"]


def test_ingest_retry_with_same_invocation_id_is_idempotent_and_does_not_refetch(
    fixed_run_time,
):
    storage = MemoryStorageClient()
    first = _ingest_fixture(storage, fixed_run_time)

    def must_not_fetch(*args, **kwargs):
        raise AssertionError("existing invocation receipt should make an exact retry a no-op")

    replay = ingest(
        observation_date="2026-11-05",
        provinces="HCM,HN,DN",
        invocation_id="test-run-001",
        now=fixed_run_time,
        storage_client=storage,
        source_fetch=must_not_fetch,
    )
    assert replay["request_id"] == first["request_id"]
    assert replay["manifest_generation"] == first["manifest_generation"]
    assert replay["execution_receipt_generation"] == first["execution_receipt_generation"]
    assert len(storage.target_bucket.objects) == 6  # 3 raw + parquet + manifest + receipt


def test_landing_merges_exact_manifest_version_and_bounds_bigquery_scan(fixed_run_time):
    storage = MemoryStorageClient()
    ingest_receipt = _ingest_fixture(storage, fixed_run_time)
    client = FakeBigQueryClient()
    result = land(
        manifest_uri=ingest_receipt["manifest_uri"],
        manifest_generation=ingest_receipt["manifest_generation"],
        storage_client=storage,
        bigquery_client=client,
    )

    assert result["status"] == "PASS"
    assert result["row_count"] == 3
    assert result["landing_table"] == LANDING_TABLE
    assert len(client.jobs) == 2
    assert client.configs[0].maximum_bytes_billed == MAXIMUM_BYTES_BILLED
    assert "observation_date = @observation_date" in client.sql[0]
    assert "request_id" in client.sql[1]
    assert "FULL OUTER JOIN" in client.sql[1]
    assert "landed_at" in client.sql[0]
    row_parameter = client.configs[0].query_parameters[0]
    serialized = row_parameter.to_api_repr()
    assert serialized["parameterType"]["arrayType"]["type"] == "STRUCT"
    assert len(serialized["parameterValue"]["arrayValues"]) == 3


def test_read_only_verify_uses_manifest_generation_and_reconciles_target(fixed_run_time):
    storage = MemoryStorageClient()
    ingest_receipt = _ingest_fixture(storage, fixed_run_time)
    client = FakeBigQueryClient()
    result = verify(
        request_id=ingest_receipt["request_id"],
        manifest_uri=ingest_receipt["manifest_uri"],
        manifest_generation=ingest_receipt["manifest_generation"],
        storage_client=storage,
        bigquery_client=client,
    )
    assert result["status"] == "PASS"
    assert len(client.jobs) == 1
    assert client.sql[0].lstrip().startswith("WITH target")


def test_manifest_and_typed_files_fail_closed_on_hash_or_generation_corruption(fixed_run_time):
    storage = MemoryStorageClient()
    receipt = _ingest_fixture(storage, fixed_run_time)
    manifest_name = receipt["manifest_uri"].split(f"gs://{BRONZE_BUCKET}/", 1)[1]
    manifest_blob = storage.target_bucket.objects[manifest_name]
    current_manifest = json.loads(manifest_blob[receipt["manifest_generation"]])
    parquet_name = current_manifest["typed_parquet"]["uri"].split(
        f"gs://{BRONZE_BUCKET}/", 1
    )[1]
    parquet_generation = current_manifest["typed_parquet"]["generation"]
    storage.target_bucket.objects[parquet_name][parquet_generation] = b"corrupted"

    with pytest.raises(WeatherJobError, match="checksum"):
        land(
            manifest_uri=receipt["manifest_uri"],
            manifest_generation=receipt["manifest_generation"],
            storage_client=storage,
            bigquery_client=FakeBigQueryClient(),
        )
    with pytest.raises(WeatherJobError, match="generation"):
        land(
            manifest_uri=receipt["manifest_uri"],
            manifest_generation=receipt["manifest_generation"] + 999,
            storage_client=storage,
            bigquery_client=FakeBigQueryClient(),
        )


def test_landing_target_is_locked_to_the_approved_project_and_region():
    sql = _landing_merge_sql()
    assert PROJECT_ID in LANDING_TABLE
    assert f"`{PROJECT_ID}.weather_mini3.weather_landing`" in sql
    assert "UNNEST(@weather_rows)" in sql


def test_landing_reconciliation_uses_columns_from_the_joined_cte():
    sql = _landing_reconciliation_sql()
    outer_select = sql.rsplit("\n    SELECT\n", maxsplit=1)[-1]
    assert "target." not in outer_select
    assert "COUNTIF(request_id IS NOT NULL) AS observed_rows" in outer_select
    assert "observation_date IS DISTINCT FROM source_observation_date" in outer_select
