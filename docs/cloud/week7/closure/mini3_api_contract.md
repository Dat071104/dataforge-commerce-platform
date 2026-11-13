# Mini-project 3 API and Bronze contract

## Scope

The optional weather slice reuses the accepted Mini-project 1 Open-Meteo
Historical Weather adapter in `src/dataforge/weather.py`. It is a separate
observation domain; it does not join to or modify Week-5 orders/payments or the
Week-7 commerce publication pointer.

This implementation accepts one historical date and at most three allowlisted
city-centre coordinates: `HCM`, `HN`, and `DN`. A request must be at least
seven `Asia/Ho_Chi_Minh` calendar days old to allow the ERA5 archive to settle.
The default date is HCM today minus seven days. Each request has one observation
date, two daily source fields (`precipitation_sum`, `temperature_2m_max`), the
`Asia/Ho_Chi_Minh` timezone, and the `era5` model.

## Container interface

The finite Cloud Run Job is named `dataforge-week7-weather-ingest`; the image
entrypoint is `python /app/cloud/jobs/week7_weather/weather_job.py`.

```text
ingest --observation-date YYYY-MM-DD --provinces HCM,HN,DN --invocation-id <stable-id>
land --manifest-uri <exact-gs-uri> --manifest-generation <positive-int>
verify --request-id <64-lowercase-hex> --manifest-uri <exact-gs-uri> --manifest-generation <positive-int>
```

`ingest` defaults to the settled date and all three provinces. It calls the
existing adapter with bounded timeouts and retries. It writes only GCS Bronze
objects and a per-invocation receipt. `land` pins the exact manifest generation,
verifies each raw response and typed Parquet generation/checksum/schema/value,
then idempotently merges the rows into BigQuery. `verify` performs a read-only
full outer reconciliation against that request's landing rows.

The JSON line printed by `ingest` and stored in the invocation receipt includes:

```json
{
  "schema_version": "dataforge.weather.mini3.execution.v1",
  "status": "COMPLETE",
  "invocation_id": "stable-orchestrator-id",
  "observation_date": "YYYY-MM-DD",
  "provinces": ["HCM", "HN", "DN"],
  "request_id": "64 lowercase hexadecimal characters",
  "manifest_uri": "gs://dataforge-p7-lab-d0f725-bronze/weather_mini3/v1/manifests/observation_date=YYYY-MM-DD/request_id=<sha256>/manifest.json",
  "manifest_generation": 123,
  "source_sha256": "64 lowercase hexadecimal characters",
  "row_count": 3,
  "provider": "Open-Meteo",
  "model": "era5",
  "settling_lag_days": 7,
  "attribution_url": "https://open-meteo.com/"
}
```

## Immutable identity and provenance

`request_id` is a bare SHA-256 digest over canonical JSON containing the
provider/endpoint, requested date, ordered province IDs and coordinates, fields,
timezone, model, and each province's successful raw-response digest. Identical
provider responses therefore replay to the same ID; a corrected provider
response receives a new ID. `source_sha256` hashes the canonical typed rows.

All object writes use the GCS `if_generation_match=0` precondition. If an object
already exists, the job verifies its bytes and reuses its immutable generation;
different bytes at the same path fail closed. Artifact paths are:

```text
weather_mini3/v1/raw/observation_date=<date>/request_id=<sha256>/province_id=<id>/sha256=<raw-sha256>.json
weather_mini3/v1/typed/observation_date=<date>/request_id=<sha256>/weather_daily.parquet
weather_mini3/v1/manifests/observation_date=<date>/request_id=<sha256>/manifest.json
weather_mini3/v1/executions/invocation_id=<stable-id>.json
```

The manifest is published only after all raw and typed artifacts are complete.
It contains the source/model/timezone/field contract, attribution, coordinates,
the per-province response hashes, the typed Parquet URI/generation/SHA-256/size,
the canonical source hash, row count, and `status=COMPLETE`. A failed manifest
or landing check never updates a weather Gold publication.

## BigQuery landing schema

The landing relation is `dataforge-p7-lab-d0f725.weather_mini3.weather_landing`,
partitioned by `observation_date` to support bounded scans.

| Field | Type | Nullability | Meaning |
|---|---|---|---|
| `province_id` | STRING | required | Allowlisted city code |
| `observation_date` | DATE | required | HCM-local daily observation date |
| `precipitation_mm` | FLOAT64 | nullable | Daily precipitation sum, millimetres |
| `temp_max_c` | FLOAT64 | nullable | Daily maximum temperature, Celsius |
| `source` | STRING | required | `open_meteo_era5` |
| `model` | STRING | required | `era5` |
| `request_id` | STRING | required | Content-addressed request/version |
| `source_sha256` | STRING | required | Digest of the canonical typed rows |
| `manifest_uri` | STRING | required | Exact immutable GCS manifest path |
| `manifest_generation` | INT64 | required | Exact manifest generation used |
| `landed_at` | TIMESTAMP | required | BigQuery merge timestamp |

Rows are unique by `(request_id, province_id, observation_date)`. A replay of
the same request is a no-op; a later provider correction creates a new
`request_id` and preserves the prior observed version. dbt Silver selects the
latest verified request per `(province_id, observation_date, source, model)`.

## Runtime boundaries

The container fixes its project, number, region, bucket, dataset, and table to
the approved DataForge target. It does not create/delete datasets or modify
Week-5 / Week-7 commerce tables. BigQuery operations set a 256 MiB billed-byte
maximum and require `weather_landing` to be partitioned by `observation_date`.
The Cloud Run identity needs create/read access only to the
`weather_mini3/v1/` object prefix, BigQuery job creation, and table read/update
access to the weather landing table. It does not need GCS list access, dataset
creation, table deletion, or write access to commerce datasets.

Offline contract tests are in `tests/mini3_api/test_weather_job.py`. They use a
mocked Open-Meteo response and in-memory GCS/BigQuery adapters; these tests do
not count as proof of a live provider request or deployed cloud execution.
