"""Finite Mini-project 3 Open-Meteo → GCS Bronze → BigQuery landing job.

The job exposes three explicit operations so Workflows and the optional Airflow
integration can orchestrate the same implementation at useful stage boundaries:

* ``ingest`` fetches one settled observation date for an allowlisted province
  subset and publishes immutable raw responses, typed Parquet, and a COMPLETE
  manifest to the approved Bronze bucket.
* ``land`` reads a manifest at its exact GCS generation, verifies every source
  artifact, and idempotently MERGEs the typed rows into the isolated weather
  landing table.
* ``verify`` is read-only and reconciles the exact manifest version with the
  landing rows.

No operation changes the accepted Week-5 order/payment pipeline or Week-7
commerce publication pointer.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from dataforge.weather import API, CITY_LOCATIONS, DAILY_FIELDS, MODEL, TIMEZONE, fetch, parse_daily

PROJECT_ID = "dataforge-p7-lab-d0f725"
PROJECT_NUMBER = "955038620072"
REGION = "us-central1"
BRONZE_BUCKET = "dataforge-p7-lab-d0f725-bronze"
BRONZE_PREFIX = "weather_mini3/v1"
LANDING_TABLE = f"{PROJECT_ID}.weather_mini3.weather_landing"
WEATHER_SOURCE = "open_meteo_era5"
SETTLING_DAYS = 7
MAXIMUM_BYTES_BILLED = 256 * 1024 * 1024
LOCAL_ZONE = ZoneInfo(TIMEZONE)
INVOCATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

PARQUET_SCHEMA = pa.schema(
    [
        pa.field("province_id", pa.string(), nullable=False),
        pa.field("observation_date", pa.date32(), nullable=False),
        pa.field("precipitation_mm", pa.float64()),
        pa.field("temp_max_c", pa.float64()),
        pa.field("source", pa.string(), nullable=False),
        pa.field("model", pa.string(), nullable=False),
    ]
)

LANDING_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("province_id", "STRING", False),
    ("observation_date", "DATE", False),
    ("precipitation_mm", "FLOAT", True),
    ("temp_max_c", "FLOAT", True),
    ("source", "STRING", False),
    ("model", "STRING", False),
    ("request_id", "STRING", False),
    ("source_sha256", "STRING", False),
    ("manifest_uri", "STRING", False),
    ("manifest_generation", "INTEGER", False),
    ("landed_at", "TIMESTAMP", False),
)


class WeatherJobError(RuntimeError):
    """Raised when Mini-project 3 input or side effects fail closed."""


@dataclass(frozen=True)
class GcsObject:
    uri: str
    generation: int
    sha256: str
    byte_size: int


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def default_observation_date(now: datetime | None = None) -> date:
    """Return the latest conservative ERA5 date using Vietnam local semantics."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise WeatherJobError("current time must be timezone-aware")
    local_today = current.astimezone(LOCAL_ZONE).date()
    return local_today - timedelta(days=SETTLING_DAYS)


def validate_observation_date(value: str | date, *, today: date | None = None) -> date:
    """Require one historical date at least seven HCM calendar days old."""
    if isinstance(value, datetime):
        raise WeatherJobError("observation date must use YYYY-MM-DD")
    try:
        observation_date = value if isinstance(value, date) else date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise WeatherJobError("observation date must use YYYY-MM-DD") from exc
    if not isinstance(observation_date, date):
        raise WeatherJobError("observation date must use YYYY-MM-DD")
    if isinstance(value, str) and observation_date.isoformat() != value:
        raise WeatherJobError("observation date must use canonical YYYY-MM-DD")
    latest_allowed = (today or datetime.now(LOCAL_ZONE).date()) - timedelta(days=SETTLING_DAYS)
    if observation_date > latest_allowed:
        raise WeatherJobError(
            f"observation date must be at least {SETTLING_DAYS} HCM calendar days settled"
        )
    return observation_date


def validate_provinces(value: str | list[str] | tuple[str, ...]) -> list[str]:
    provinces = value.split(",") if isinstance(value, str) else list(value)
    provinces = [province.strip() for province in provinces]
    if not provinces or any(not province for province in provinces):
        raise WeatherJobError("at least one province is required")
    if len(provinces) > len(CITY_LOCATIONS):
        raise WeatherJobError("province count exceeds the three-city request bound")
    if len(set(provinces)) != len(provinces):
        raise WeatherJobError("province list must not contain duplicates")
    if any(province not in CITY_LOCATIONS for province in provinces):
        raise WeatherJobError(f"allowed provinces are {','.join(CITY_LOCATIONS)}")
    return provinces


def validate_invocation_id(value: str) -> str:
    if not INVOCATION_ID_PATTERN.fullmatch(value):
        raise WeatherJobError("invocation_id must be 1–64 letters, digits, underscores, or hyphens")
    return value


def _source_rows_from_csv(path: Path, observation_date: date, provinces: list[str]) -> list[dict]:
    expected_header = [
        "province_id",
        "observation_date",
        "precipitation_mm",
        "temp_max_c",
        "source",
    ]
    rows: list[dict] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != expected_header:
            raise WeatherJobError("Open-Meteo adapter returned an unexpected CSV schema")
        for raw in reader:
            province = raw["province_id"]
            if province not in provinces or raw["source"] != WEATHER_SOURCE:
                raise WeatherJobError("Open-Meteo adapter returned an unexpected province or source")
            if raw["observation_date"] != observation_date.isoformat():
                raise WeatherJobError("Open-Meteo adapter returned an unexpected date")
            rain = _parse_optional_finite_float(raw["precipitation_mm"], "precipitation_mm")
            temperature = _parse_optional_finite_float(raw["temp_max_c"], "temp_max_c")
            if rain is not None and rain < 0:
                raise WeatherJobError("precipitation_mm must not be negative")
            rows.append(
                {
                    "province_id": province,
                    "observation_date": observation_date,
                    "precipitation_mm": rain,
                    "temp_max_c": temperature,
                    "source": WEATHER_SOURCE,
                    "model": MODEL,
                }
            )
    row_keys = [(row["province_id"], row["observation_date"]) for row in rows]
    expected_keys = [(province, observation_date) for province in provinces]
    if row_keys != expected_keys:
        raise WeatherJobError("Open-Meteo adapter returned missing, duplicate, or unordered province dates")
    return rows


def _parse_optional_finite_float(value: str | None, field: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise WeatherJobError(f"{field} must be numeric or null") from exc
    if not math.isfinite(parsed):
        raise WeatherJobError(f"{field} must be finite")
    return parsed


def _canonical_rows(rows: list[dict]) -> list[dict]:
    return [
        {
            "province_id": row["province_id"],
            "observation_date": row["observation_date"].isoformat(),
            "precipitation_mm": row["precipitation_mm"],
            "temp_max_c": row["temp_max_c"],
            "source": row["source"],
            "model": row["model"],
        }
        for row in rows
    ]


def build_request_id(
    *,
    observation_date: date,
    provinces: list[str],
    response_sha256_by_province: dict[str, str],
) -> str:
    if set(response_sha256_by_province) != set(provinces):
        raise WeatherJobError("one successful raw response digest is required per province")
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in response_sha256_by_province.values()):
        raise WeatherJobError("provider response digests must be lowercase SHA-256 hex")
    identity = {
        "provider": "Open-Meteo",
        "endpoint": API,
        "observation_date": observation_date.isoformat(),
        "provinces": [
            {
                "province_id": province,
                "latitude": CITY_LOCATIONS[province][0],
                "longitude": CITY_LOCATIONS[province][1],
                "response_sha256": response_sha256_by_province[province],
            }
            for province in provinces
        ],
        "daily_fields": list(DAILY_FIELDS),
        "timezone": TIMEZONE,
        "model": MODEL,
    }
    return _sha256(_canonical_json(identity))


def _object_uri(object_name: str) -> str:
    return f"gs://{BRONZE_BUCKET}/{object_name}"


def _ensure_approved_environment() -> None:
    """Refuse a container configured for an unapproved project or bucket."""
    import os

    configured_project = os.environ.get("DATAFORGE_PROJECT_ID", PROJECT_ID)
    configured_bucket = os.environ.get("DATAFORGE_WEATHER_BUCKET", BRONZE_BUCKET)
    if configured_project != PROJECT_ID or configured_bucket != BRONZE_BUCKET:
        raise WeatherJobError("runtime target differs from the approved DataForge project or bucket")


def _gcs_clients(storage_client: Any | None = None) -> tuple[Any, Any]:
    if storage_client is None:
        from google.cloud import storage

        storage_client = storage.Client(project=PROJECT_ID)
    return storage_client, storage_client.bucket(BRONZE_BUCKET)


def _read_versioned_blob(bucket: Any, object_name: str, generation: int | None = None) -> tuple[bytes, int]:
    from google.api_core.exceptions import NotFound

    try:
        if generation is None:
            versioned = bucket.blob(object_name)
            versioned.reload()
        else:
            versioned = bucket.blob(object_name, generation=int(generation))
            versioned.reload()
    except NotFound as exc:
        if generation is not None:
            raise WeatherJobError(
                f"requested Bronze generation {generation} does not exist: {object_name}"
            ) from exc
        raise WeatherJobError(f"required Bronze object does not exist: {object_name}") from exc
    actual_generation = int(versioned.generation)
    if generation is not None and actual_generation != int(generation):
        raise WeatherJobError("Bronze object generation does not match the supplied manifest identity")
    payload = versioned.download_as_bytes()
    if int(versioned.generation or actual_generation) != actual_generation:
        raise WeatherJobError("Bronze download returned a different object generation")
    return payload, actual_generation


def _upload_if_absent(bucket: Any, object_name: str, payload: bytes, content_type: str) -> GcsObject:
    from google.api_core.exceptions import PreconditionFailed

    blob = bucket.blob(object_name)
    expected_hash = _sha256(payload)
    try:
        blob.upload_from_string(
            payload,
            content_type=content_type,
            if_generation_match=0,
            checksum="crc32c",
        )
        generation = int(blob.generation)
    except PreconditionFailed:
        stored, generation = _read_versioned_blob(bucket, object_name)
        if _sha256(stored) != expected_hash:
            raise WeatherJobError(
                f"immutable Bronze object already exists with different bytes: {object_name}"
            )
    return GcsObject(
        uri=_object_uri(object_name),
        generation=generation,
        sha256=expected_hash,
        byte_size=len(payload),
    )


def _read_json_uri(
    bucket: Any,
    uri: str,
    *,
    expected_generation: int | None = None,
) -> tuple[dict, int, bytes]:
    object_name = _object_name_from_uri(uri)
    payload, generation = _read_versioned_blob(bucket, object_name, expected_generation)
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WeatherJobError("Bronze JSON object is invalid") from exc
    if not isinstance(document, dict):
        raise WeatherJobError("Bronze JSON document must be an object")
    return document, generation, payload


def _object_name_from_uri(uri: str) -> str:
    prefix = f"gs://{BRONZE_BUCKET}/"
    if not isinstance(uri, str) or not uri.startswith(prefix):
        raise WeatherJobError("manifest URI must point to the approved Bronze bucket")
    object_name = uri[len(prefix) :]
    if not object_name.startswith(f"{BRONZE_PREFIX}/") or ".." in object_name.split("/"):
        raise WeatherJobError("manifest URI must point inside the Mini-project 3 prefix")
    return object_name


def _manifest_path(observation_date: date, request_id: str) -> str:
    return (
        f"{BRONZE_PREFIX}/manifests/observation_date={observation_date.isoformat()}"
        f"/request_id={request_id}/manifest.json"
    )


def _execution_receipt_path(invocation_id: str) -> str:
    return f"{BRONZE_PREFIX}/executions/invocation_id={invocation_id}.json"


def _rows_to_parquet(rows: list[dict]) -> bytes:
    table = pa.Table.from_pylist(rows, schema=PARQUET_SCHEMA)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        version="2.6",
    )
    return sink.getvalue().to_pybytes()


def _extract_successful_responses(provenance: dict, scratch: Path, provinces: list[str]) -> dict[str, dict]:
    successful: dict[str, dict] = {}
    for response in provenance.get("responses", []):
        if response.get("http_status") == 200 and response.get("raw_response_json"):
            successful[response["province_id"]] = response
    if set(successful) != set(provinces):
        raise WeatherJobError("source provenance is missing a successful provider response for a province")
    for province, response in successful.items():
        relative = Path(response["raw_response_json"])
        if relative.is_absolute() or ".." in relative.parts:
            raise WeatherJobError("source adapter returned an unsafe raw response path")
        raw_path = scratch / relative
        if not raw_path.is_file():
            raise WeatherJobError(f"source adapter raw response is missing for {province}")
        raw_bytes = raw_path.read_bytes()
        if _sha256(raw_bytes) != response.get("response_sha256"):
            raise WeatherJobError(f"source adapter raw response digest mismatch for {province}")
        try:
            payload = json.loads(raw_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WeatherJobError(f"raw response for {province} is not valid JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("daily"), dict):
            raise WeatherJobError(f"raw response for {province} has no daily object")
    return successful


def _replay_execution_receipt(bucket: Any, invocation_id: str, observation_date: date,
                              provinces: list[str]) -> dict | None:
    object_name = _execution_receipt_path(invocation_id)
    try:
        document, generation, _ = _read_json_uri(bucket, _object_uri(object_name))
    except WeatherJobError as exc:
        if "does not exist" in str(exc):
            return None
        raise
    expected_provinces = document.get("provinces")
    if (
        document.get("status") != "COMPLETE"
        or document.get("invocation_id") != invocation_id
        or document.get("observation_date") != observation_date.isoformat()
        or expected_provinces != provinces
    ):
        raise WeatherJobError("invocation_id already names a different or incomplete execution receipt")
    document["execution_receipt_generation"] = generation
    return document


def ingest(
    *,
    observation_date: str | date,
    provinces: str | list[str] | tuple[str, ...] = "HCM,HN,DN",
    invocation_id: str | None = None,
    now: datetime | None = None,
    storage_client: Any | None = None,
    source_fetch: Callable[..., int] = fetch,
) -> dict:
    """Fetch, validate, and immutably publish one bounded source request."""
    _ensure_approved_environment()
    if now is not None and now.tzinfo is None:
        raise WeatherJobError("current time must be timezone-aware")
    parsed_date = validate_observation_date(
        observation_date,
        today=(now.astimezone(LOCAL_ZONE).date() if now else None),
    )
    requested_provinces = validate_provinces(provinces)
    invocation = validate_invocation_id(invocation_id or _new_invocation_id())
    _, bucket = _gcs_clients(storage_client)

    existing = _replay_execution_receipt(bucket, invocation, parsed_date, requested_provinces)
    if existing is not None:
        return existing

    with TemporaryDirectory(prefix="dataforge-weather-mini3-") as temporary:
        scratch = Path(temporary)
        source_fetch(
            parsed_date,
            parsed_date,
            provinces=requested_provinces,
            dest=scratch,
        )
        source_path = scratch / "weather_daily.csv"
        provenance_path = scratch / ".open_meteo" / "weather_provenance.json"
        if not source_path.is_file() or not provenance_path.is_file():
            raise WeatherJobError("Open-Meteo adapter did not produce source and provenance artifacts")
        rows = _source_rows_from_csv(source_path, parsed_date, requested_provinces)
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WeatherJobError("Open-Meteo adapter provenance is invalid") from exc
        if (
            provenance.get("status") != "complete"
            or provenance.get("provider") != "Open-Meteo"
            or provenance.get("model") != MODEL
            or provenance.get("timezone") != TIMEZONE
            or provenance.get("weather_csv_rows") != len(rows)
            or provenance.get("date_range") != {
                "start": parsed_date.isoformat(),
                "end": parsed_date.isoformat(),
            }
        ):
            raise WeatherJobError("Open-Meteo provenance does not match the requested contract")
        successful = _extract_successful_responses(provenance, scratch, requested_provinces)
        response_digests = {
            province: successful[province]["response_sha256"] for province in requested_provinces
        }
        request_id = build_request_id(
            observation_date=parsed_date,
            provinces=requested_provinces,
            response_sha256_by_province=response_digests,
        )
        source_sha256 = _sha256(_canonical_json(_canonical_rows(rows)))

        raw_objects: list[dict] = []
        for province in requested_provinces:
            response = successful[province]
            raw_path = scratch / response["raw_response_json"]
            raw_bytes = raw_path.read_bytes()
            raw_object_name = (
                f"{BRONZE_PREFIX}/raw/observation_date={parsed_date.isoformat()}"
                f"/request_id={request_id}/province_id={province}"
                f"/sha256={response_digests[province]}.json"
            )
            uploaded = _upload_if_absent(bucket, raw_object_name, raw_bytes, "application/json")
            raw_objects.append(
                {
                    "province_id": province,
                    "uri": uploaded.uri,
                    "generation": uploaded.generation,
                    "sha256": uploaded.sha256,
                    "byte_size": uploaded.byte_size,
                    "http_status": 200,
                    "provider_response_sha256": response_digests[province],
                }
            )

        parquet_bytes = _rows_to_parquet(rows)
        parquet_path = (
            f"{BRONZE_PREFIX}/typed/observation_date={parsed_date.isoformat()}"
            f"/request_id={request_id}/weather_daily.parquet"
        )
        parquet_object = _upload_if_absent(bucket, parquet_path, parquet_bytes, "application/vnd.apache.parquet")

        province_metadata = provenance.get("requested_provinces", [])
        if [entry.get("province_id") for entry in province_metadata] != requested_provinces:
            raise WeatherJobError("Open-Meteo province metadata differs from the requested order")
        manifest = {
            "schema_version": "dataforge.weather.mini3.v1",
            "status": "COMPLETE",
            "request_id": request_id,
            "observation_date": parsed_date.isoformat(),
            "requested_provinces": province_metadata,
            "provider": {
                "name": "Open-Meteo",
                "endpoint": API,
                "model": MODEL,
                "timezone": TIMEZONE,
                "daily_fields": list(DAILY_FIELDS),
                "attribution": provenance["attribution"],
            },
            "response_sha256_by_province": response_digests,
            "raw_responses": raw_objects,
            "source_sha256": source_sha256,
            "row_count": len(rows),
            "typed_parquet": {
                "uri": parquet_object.uri,
                "generation": parquet_object.generation,
                "sha256": parquet_object.sha256,
                "byte_size": parquet_object.byte_size,
                "schema": [
                    {"name": field.name, "type": str(field.type), "nullable": field.nullable}
                    for field in PARQUET_SCHEMA
                ],
            },
        }
        manifest_path = _manifest_path(parsed_date, request_id)
        manifest_object = _upload_if_absent(
            bucket, manifest_path, _canonical_json(manifest) + b"\n", "application/json"
        )
        receipt = {
            "schema_version": "dataforge.weather.mini3.execution.v1",
            "status": "COMPLETE",
            "invocation_id": invocation,
            "observation_date": parsed_date.isoformat(),
            "provinces": requested_provinces,
            "request_id": request_id,
            "manifest_uri": manifest_object.uri,
            "manifest_generation": manifest_object.generation,
            "source_sha256": source_sha256,
            "row_count": len(rows),
            "provider": "Open-Meteo",
            "model": MODEL,
            "settling_lag_days": SETTLING_DAYS,
            "attribution_url": "https://open-meteo.com/",
        }
        receipt_path = _execution_receipt_path(invocation)
        receipt_object = _upload_if_absent(
            bucket, receipt_path, _canonical_json(receipt) + b"\n", "application/json"
        )
        receipt["execution_receipt_generation"] = receipt_object.generation
        return receipt


def _verify_manifest_document(
    manifest: dict,
    *,
    manifest_uri: str,
    manifest_generation: int,
    bucket: Any,
    require_rows: bool = True,
) -> tuple[dict, list[dict]]:
    object_name = _object_name_from_uri(manifest_uri)
    path_match = re.fullmatch(
        rf"{re.escape(BRONZE_PREFIX)}/manifests/observation_date=(\d{{4}}-\d{{2}}-\d{{2}})"
        r"/request_id=([0-9a-f]{64})/manifest\.json",
        object_name,
    )
    if not path_match:
        raise WeatherJobError("manifest object path does not match the Mini-project 3 contract")
    path_date, path_request_id = path_match.groups()
    try:
        parsed_date = date.fromisoformat(path_date)
    except ValueError as exc:
        raise WeatherJobError("manifest path contains an invalid observation date") from exc
    raw_province_metadata = manifest.get("requested_provinces")
    if not isinstance(raw_province_metadata, list) or any(
        not isinstance(entry, dict) for entry in raw_province_metadata
    ):
        raise WeatherJobError("manifest province metadata must be a list of objects")
    provinces = validate_provinces([entry.get("province_id") for entry in raw_province_metadata])
    if (
        manifest.get("schema_version") != "dataforge.weather.mini3.v1"
        or manifest.get("status") != "COMPLETE"
        or manifest.get("request_id") != path_request_id
        or manifest.get("observation_date") != parsed_date.isoformat()
        or manifest.get("provider", {}).get("name") != "Open-Meteo"
        or manifest.get("provider", {}).get("endpoint") != API
        or manifest.get("provider", {}).get("model") != MODEL
        or manifest.get("provider", {}).get("timezone") != TIMEZONE
        or manifest.get("provider", {}).get("daily_fields") != list(DAILY_FIELDS)
        or not isinstance(manifest.get("source_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", manifest["source_sha256"])
        or not isinstance(manifest_generation, int)
        or manifest_generation <= 0
    ):
        raise WeatherJobError("manifest metadata does not satisfy the Mini-project 3 contract")
    province_metadata = raw_province_metadata
    expected_metadata = [
        {
            "province_id": province,
            "latitude": CITY_LOCATIONS[province][0],
            "longitude": CITY_LOCATIONS[province][1],
        }
        for province in provinces
    ]
    if province_metadata != expected_metadata:
        raise WeatherJobError("manifest province and coordinate metadata differs from the source contract")
    raw_responses = manifest.get("raw_responses")
    if not isinstance(raw_responses, list) or len(raw_responses) != len(provinces):
        raise WeatherJobError("manifest must include one successful raw response per province")
    response_digests: dict[str, str] = {}
    for province, raw in zip(provinces, raw_responses):
        if not isinstance(raw, dict):
            raise WeatherJobError("manifest raw response metadata is malformed")
        if (
            raw.get("province_id") != province
            or raw.get("http_status") != 200
            or not re.fullmatch(r"[0-9a-f]{64}", str(raw.get("sha256", "")))
            or raw.get("provider_response_sha256") != raw.get("sha256")
            or not isinstance(raw.get("generation"), int)
            or raw["generation"] <= 0
            or not isinstance(raw.get("byte_size"), int)
            or raw["byte_size"] <= 0
        ):
            raise WeatherJobError("manifest raw response metadata is malformed")
        expected_raw_path = (
            f"{BRONZE_PREFIX}/raw/observation_date={parsed_date.isoformat()}"
            f"/request_id={path_request_id}/province_id={province}"
            f"/sha256={raw['sha256']}.json"
        )
        if raw.get("uri") != _object_uri(expected_raw_path):
            raise WeatherJobError("manifest raw response URI is outside its immutable request path")
        response_digests[province] = raw["provider_response_sha256"]
    if manifest.get("response_sha256_by_province") != response_digests:
        raise WeatherJobError("manifest provider response digest map does not match raw artifacts")
    expected_request_id = build_request_id(
        observation_date=parsed_date,
        provinces=provinces,
        response_sha256_by_province=response_digests,
    )
    if expected_request_id != path_request_id:
        raise WeatherJobError("manifest request_id does not reconcile to its provider response digests")
    parquet_info = manifest.get("typed_parquet")
    if not isinstance(parquet_info, dict):
        raise WeatherJobError("manifest typed Parquet metadata is missing")
    if parquet_info.get("schema") != [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in PARQUET_SCHEMA
    ]:
        raise WeatherJobError("manifest typed Parquet schema differs from the approved contract")
    if (
        not isinstance(parquet_info.get("generation"), int)
        or parquet_info["generation"] <= 0
        or not re.fullmatch(r"[0-9a-f]{64}", str(parquet_info.get("sha256", "")))
        or not isinstance(parquet_info.get("uri"), str)
        or not isinstance(parquet_info.get("byte_size"), int)
        or parquet_info["byte_size"] <= 0
    ):
        raise WeatherJobError("manifest typed Parquet identity is malformed")
    expected_parquet_path = (
        f"{BRONZE_PREFIX}/typed/observation_date={parsed_date.isoformat()}"
        f"/request_id={path_request_id}/weather_daily.parquet"
    )
    if parquet_info["uri"] != _object_uri(expected_parquet_path):
        raise WeatherJobError("manifest typed Parquet URI is outside its immutable request path")
    rows = []
    if require_rows:
        rows = _read_and_validate_parquet(bucket, parquet_info, manifest, parsed_date, provinces)
        for province, raw in zip(provinces, raw_responses):
            raw_bytes, _ = _read_versioned_blob(
                bucket,
                _object_name_from_uri(raw.get("uri")),
                raw["generation"],
            )
            if _sha256(raw_bytes) != raw["sha256"] or len(raw_bytes) != raw["byte_size"]:
                raise WeatherJobError(f"raw provider response checksum or size mismatch for {province}")
            try:
                raw_payload = json.loads(raw_bytes)
                parsed_raw = parse_daily(raw_payload, province)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise WeatherJobError(f"raw provider response is invalid for {province}") from exc
            matching = [row for row in rows if row["province_id"] == province]
            if len(parsed_raw) != 1 or len(matching) != 1 or parsed_raw[0] != (
                province,
                parsed_date.isoformat(),
                matching[0]["precipitation_mm"],
                matching[0]["temp_max_c"],
                WEATHER_SOURCE,
            ):
                raise WeatherJobError(f"raw and typed weather values do not reconcile for {province}")
    return {
        "observation_date": parsed_date,
        "provinces": provinces,
        "request_id": path_request_id,
        "source_sha256": manifest["source_sha256"],
        "parquet": parquet_info,
        "raw_responses": raw_responses,
        "row_count": manifest.get("row_count"),
        "manifest_uri": manifest_uri,
        "manifest_generation": manifest_generation,
    }, rows


def _read_and_validate_parquet(bucket: Any, parquet_info: dict, manifest: dict,
                               observation_date: date, provinces: list[str]) -> list[dict]:
    object_name = _object_name_from_uri(parquet_info["uri"])
    payload, generation = _read_versioned_blob(bucket, object_name, parquet_info["generation"])
    if _sha256(payload) != parquet_info["sha256"] or len(payload) != parquet_info["byte_size"]:
        raise WeatherJobError("typed Parquet checksum or size mismatch")
    try:
        table = pq.read_table(io.BytesIO(payload))
    except (pa.ArrowException, OSError) as exc:
        raise WeatherJobError("typed Parquet object cannot be decoded") from exc
    if table.schema.remove_metadata() != PARQUET_SCHEMA:
        raise WeatherJobError("typed Parquet schema differs from the approved contract")
    rows = table.to_pylist()
    if len(rows) != manifest.get("row_count") or len(rows) != len(provinces):
        raise WeatherJobError("typed Parquet row count differs from its manifest")
    if [(row["province_id"], row["observation_date"]) for row in rows] != [
        (province, observation_date) for province in provinces
    ]:
        raise WeatherJobError("typed Parquet has missing, duplicate, or unexpected province dates")
    for row in rows:
        if row["source"] != WEATHER_SOURCE or row["model"] != MODEL:
            raise WeatherJobError("typed Parquet source/model tags differ from the contract")
        rain = row["precipitation_mm"]
        temperature = row["temp_max_c"]
        if rain is not None and (not math.isfinite(rain) or rain < 0):
            raise WeatherJobError("typed Parquet has invalid precipitation")
        if temperature is not None and not math.isfinite(temperature):
            raise WeatherJobError("typed Parquet has invalid maximum temperature")
    if _sha256(_canonical_json(_canonical_rows(rows))) != manifest["source_sha256"]:
        raise WeatherJobError("typed Parquet rows do not match source_sha256")
    return rows


def _load_exact_manifest(bucket: Any, manifest_uri: str, generation: int) -> tuple[dict, bytes]:
    if not isinstance(generation, int) or generation <= 0:
        raise WeatherJobError("manifest generation must be a positive integer")
    document, observed_generation, payload = _read_json_uri(
        bucket,
        manifest_uri,
        expected_generation=generation,
    )
    if observed_generation != generation:
        raise WeatherJobError("manifest generation changed during read")
    return document, payload


def _bigquery_client(bigquery_client: Any | None = None) -> Any:
    if bigquery_client is None:
        from google.cloud import bigquery

        bigquery_client = bigquery.Client(project=PROJECT_ID, location=REGION)
    return bigquery_client


def _verify_landing_schema(client: Any) -> None:
    table = client.get_table(LANDING_TABLE)
    actual = {field.name: (field.field_type, field.mode == "REQUIRED") for field in table.schema}
    expected = {name: (kind, not nullable) for name, kind, nullable in LANDING_FIELDS}
    if actual != expected:
        raise WeatherJobError("weather landing table schema differs from the approved contract")
    partition_field = getattr(getattr(table, "time_partitioning", None), "field", None)
    if partition_field != "observation_date":
        raise WeatherJobError("weather landing table must be partitioned by observation_date")


def _build_weather_rows_parameter(rows: list[dict], identity: dict) -> tuple[Any, Any]:
    from google.cloud import bigquery

    parameter_fields = (
        ("province_id", "STRING"),
        ("observation_date", "DATE"),
        ("precipitation_mm", "FLOAT64"),
        ("temp_max_c", "FLOAT64"),
        ("source", "STRING"),
        ("model", "STRING"),
        ("request_id", "STRING"),
        ("source_sha256", "STRING"),
        ("manifest_uri", "STRING"),
        ("manifest_generation", "INT64"),
    )
    type_fields = [bigquery.ScalarQueryParameterType(kind, name=name) for name, kind in parameter_fields]
    struct_type = bigquery.StructQueryParameterType(*type_fields)
    struct_rows = []
    for row in rows:
        values = {
            **row,
            "request_id": identity["request_id"],
            "source_sha256": identity["source_sha256"],
            "manifest_uri": identity["manifest_uri"],
            "manifest_generation": identity["manifest_generation"],
        }
        struct_rows.append(
            bigquery.StructQueryParameter(
                None,
                *[
                    bigquery.ScalarQueryParameter(name, kind, values[name])
                    for name, kind in parameter_fields
                ],
            )
        )
    return bigquery.ArrayQueryParameter("weather_rows", struct_type, struct_rows), bigquery.ScalarQueryParameter(
        "request_id", "STRING", identity["request_id"]
    )


def _landing_merge_sql() -> str:
    return f"""
    MERGE `{LANDING_TABLE}` AS target
    USING UNNEST(@weather_rows) AS source
      ON target.observation_date = @observation_date
     AND target.province_id = source.province_id
     AND target.request_id = source.request_id
    WHEN NOT MATCHED THEN
      INSERT (province_id, observation_date, precipitation_mm, temp_max_c, source, model,
              request_id, source_sha256, manifest_uri, manifest_generation, landed_at)
      VALUES (source.province_id, source.observation_date, source.precipitation_mm,
              source.temp_max_c, source.source, source.model, source.request_id,
              source.source_sha256, source.manifest_uri, source.manifest_generation,
              CURRENT_TIMESTAMP())
    """


def _landing_reconciliation_sql() -> str:
    return f"""
    WITH target AS (
      SELECT province_id, observation_date, precipitation_mm, temp_max_c, source, model,
             request_id, source_sha256, manifest_uri, manifest_generation
      FROM `{LANDING_TABLE}`
      WHERE observation_date = @observation_date AND request_id = @request_id
    ), joined AS (
      SELECT source.province_id AS source_province_id,
             source.observation_date AS source_observation_date,
             source.precipitation_mm AS source_precipitation_mm,
             source.temp_max_c AS source_temp_max_c,
             source.source AS source_source,
             source.model AS source_model,
             source.request_id AS source_request_id,
             source.source_sha256 AS source_source_sha256,
             source.manifest_uri AS source_manifest_uri,
             source.manifest_generation AS source_manifest_generation,
             target.*
      FROM UNNEST(@weather_rows) AS source
      FULL OUTER JOIN target
        ON target.province_id = source.province_id
       AND target.observation_date = source.observation_date
       AND target.request_id = source.request_id
    )
    SELECT
      COUNTIF(source_request_id IS NOT NULL) AS expected_rows,
      COUNTIF(request_id IS NOT NULL) AS observed_rows,
      COUNTIF(source_request_id IS NOT NULL AND request_id IS NOT NULL) AS matched_rows,
      COUNTIF(source_request_id IS NOT NULL AND request_id IS NULL) AS missing_rows,
      COUNTIF(source_request_id IS NULL AND request_id IS NOT NULL) AS unexpected_rows,
      COUNTIF(source_request_id IS NOT NULL AND request_id IS NOT NULL AND (
        observation_date IS DISTINCT FROM source_observation_date
        OR precipitation_mm IS DISTINCT FROM source_precipitation_mm
        OR temp_max_c IS DISTINCT FROM source_temp_max_c
        OR source IS DISTINCT FROM source_source
        OR model IS DISTINCT FROM source_model
        OR source_sha256 IS DISTINCT FROM source_source_sha256
        OR manifest_uri IS DISTINCT FROM source_manifest_uri
        OR manifest_generation IS DISTINCT FROM source_manifest_generation
      )) AS mismatched_rows
    FROM joined
    """


def land(
    *,
    manifest_uri: str,
    manifest_generation: int,
    storage_client: Any | None = None,
    bigquery_client: Any | None = None,
) -> dict:
    """Verify immutable GCS inputs and idempotently MERGE their rows to BigQuery."""
    _ensure_approved_environment()
    _, bucket = _gcs_clients(storage_client)
    manifest, _ = _load_exact_manifest(bucket, manifest_uri, manifest_generation)
    identity, rows = _verify_manifest_document(
        manifest,
        manifest_uri=manifest_uri,
        manifest_generation=manifest_generation,
        bucket=bucket,
    )
    client = _bigquery_client(bigquery_client)
    _verify_landing_schema(client)
    weather_rows_param, request_id_param = _build_weather_rows_parameter(rows, identity)
    merge_config = _query_config(
        [
            weather_rows_param,
            _date_parameter(identity["observation_date"]),
        ],
        "land",
    )
    merge_job = client.query(_landing_merge_sql(), job_config=merge_config, location=REGION)
    merge_job.result(timeout=180)
    reconciliation_config = _query_config(
        [weather_rows_param, request_id_param, _date_parameter(identity["observation_date"])],
        "verify",
    )
    reconciliation_job = client.query(
        _landing_reconciliation_sql(), job_config=reconciliation_config, location=REGION
    )
    reconciled = next(iter(reconciliation_job.result(timeout=180)))
    counts = {field: int(reconciled[field] or 0) for field in (
        "expected_rows", "observed_rows", "matched_rows", "missing_rows", "unexpected_rows", "mismatched_rows"
    )}
    if (
        counts["expected_rows"] != len(rows)
        or counts["observed_rows"] != len(rows)
        or counts["matched_rows"] != len(rows)
        or counts["missing_rows"] != 0
        or counts["unexpected_rows"] != 0
        or counts["mismatched_rows"] != 0
    ):
        raise WeatherJobError("BigQuery weather landing reconciliation failed")
    return {
        "status": "PASS",
        "project_id": PROJECT_ID,
        "region": REGION,
        "landing_table": LANDING_TABLE,
        "query_job_id": getattr(merge_job, "job_id", None),
        "reconciliation_job_id": getattr(reconciliation_job, "job_id", None),
        "bytes_billed": int(getattr(merge_job, "total_bytes_billed", 0) or 0)
        + int(getattr(reconciliation_job, "total_bytes_billed", 0) or 0),
        "request_id": identity["request_id"],
        "manifest_uri": manifest_uri,
        "manifest_generation": manifest_generation,
        "source_sha256": identity["source_sha256"],
        "row_count": counts["matched_rows"],
        "reconciliation": counts,
    }


def _date_parameter(value: date) -> Any:
    from google.cloud import bigquery

    return bigquery.ScalarQueryParameter("observation_date", "DATE", value)


def _query_config(parameters: list[Any], action: str) -> Any:
    from google.cloud import bigquery

    return bigquery.QueryJobConfig(
        query_parameters=parameters,
        maximum_bytes_billed=MAXIMUM_BYTES_BILLED,
        labels={"application": "dataforge", "phase": "week7", "domain": "weather", "action": action},
    )


def verify(
    *,
    request_id: str,
    manifest_uri: str,
    manifest_generation: int,
    storage_client: Any | None = None,
    bigquery_client: Any | None = None,
) -> dict:
    """Read-only evidence check for a complete, exact-generation landing batch."""
    _ensure_approved_environment()
    _, bucket = _gcs_clients(storage_client)
    manifest, _ = _load_exact_manifest(bucket, manifest_uri, manifest_generation)
    identity, rows = _verify_manifest_document(
        manifest,
        manifest_uri=manifest_uri,
        manifest_generation=manifest_generation,
        bucket=bucket,
    )
    if identity["request_id"] != request_id:
        raise WeatherJobError("requested request_id does not match the exact manifest")
    client = _bigquery_client(bigquery_client)
    _verify_landing_schema(client)
    weather_rows_param, request_id_param = _build_weather_rows_parameter(rows, identity)
    config = _query_config(
        [weather_rows_param, request_id_param, _date_parameter(identity["observation_date"])],
        "verify",
    )
    job = client.query(_landing_reconciliation_sql(), job_config=config, location=REGION)
    reconciled = next(iter(job.result(timeout=180)))
    counts = {field: int(reconciled[field] or 0) for field in (
        "expected_rows", "observed_rows", "matched_rows", "missing_rows", "unexpected_rows", "mismatched_rows"
    )}
    passed = (
        counts["expected_rows"] == len(rows)
        and counts["observed_rows"] == len(rows)
        and counts["matched_rows"] == len(rows)
        and counts["missing_rows"] == 0
        and counts["unexpected_rows"] == 0
        and counts["mismatched_rows"] == 0
    )
    if not passed:
        raise WeatherJobError("read-only BigQuery weather landing verification failed")
    return {
        "status": "PASS",
        "project_id": PROJECT_ID,
        "region": REGION,
        "landing_table": LANDING_TABLE,
        "query_job_id": getattr(job, "job_id", None),
        "bytes_billed": int(getattr(job, "total_bytes_billed", 0) or 0),
        "request_id": request_id,
        "manifest_uri": manifest_uri,
        "manifest_generation": manifest_generation,
        "source_sha256": identity["source_sha256"],
        "row_count": counts["matched_rows"],
        "reconciliation": counts,
    }


def _new_invocation_id() -> str:
    from uuid import uuid4

    return uuid4().hex


def _handle_ingest(args: argparse.Namespace) -> dict:
    return ingest(
        observation_date=args.observation_date or default_observation_date(),
        provinces=args.provinces,
        invocation_id=args.invocation_id,
    )


def _handle_land(args: argparse.Namespace) -> dict:
    return land(
        manifest_uri=args.manifest_uri,
        manifest_generation=args.manifest_generation,
    )


def _handle_verify(args: argparse.Namespace) -> dict:
    return verify(
        request_id=args.request_id,
        manifest_uri=args.manifest_uri,
        manifest_generation=args.manifest_generation,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_parser = commands.add_parser("ingest", help="fetch one settled date and publish immutable GCS Bronze")
    ingest_parser.add_argument("--observation-date", help="HCM date YYYY-MM-DD; defaults to HCM today minus 7 days")
    ingest_parser.add_argument("--provinces", default="HCM,HN,DN")
    ingest_parser.add_argument("--invocation-id", help="stable 1–64 character ID used by an orchestrator retry")
    ingest_parser.set_defaults(handler=_handle_ingest)

    land_parser = commands.add_parser("land", help="verify immutable Bronze and load typed BigQuery landing")
    land_parser.add_argument("--manifest-uri", required=True)
    land_parser.add_argument("--manifest-generation", required=True, type=int)
    land_parser.set_defaults(handler=_handle_land)

    verify_parser = commands.add_parser("verify", help="reconcile a manifest with BigQuery without mutation")
    verify_parser.add_argument("--request-id", required=True)
    verify_parser.add_argument("--manifest-uri", required=True)
    verify_parser.add_argument("--manifest-generation", required=True, type=int)
    verify_parser.set_defaults(handler=_handle_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        receipt = args.handler(args)
    except Exception as exc:
        safe_error = str(exc) if isinstance(exc, WeatherJobError) else type(exc).__name__
        print(
            json.dumps(
                {"status": "FAILED", "command": args.command, "error": safe_error},
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(json.dumps(receipt, sort_keys=True, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
