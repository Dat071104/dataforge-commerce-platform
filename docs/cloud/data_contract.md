# Week-4 GCS and BigQuery data contract

## Truth labels

- **Observed:** the active synthetic run has 11 sources. Every Parquet field is physically Arrow `string`, even when the local SQL schema is DATE, INTEGER, or NUMERIC.
- **Defined:** this adapter uses an explicit typed cloud contract matching `configs/sources.csv`, the validator's date/numeric rules, and `sql/schema/001_init.sql`.
- **Not claimed:** local snapshot loading is not CDC. It does not contain a trustworthy event watermark, delete tombstone stream, or source change journal.

## Source grain, key, and logical staging types

All source fields are physically STRING in current DataForge Parquet. BigQuery first loads the exact original Parquet bytes to a batch-scoped raw staging table with nullable STRING columns, then explicitly casts them into a separate typed staging table. This two-step load is required because Parquet is self-describing and the current DataForge Parquet files encode the date/numeric values as strings. The BigQuery load job does not reinterpret those bytes as typed dates or decimals automatically.

| Source | Grain / primary key | Typed BigQuery columns |
|---|---|---|
| geography | province | `province_id STRING`, `province STRING`, `region STRING` |
| customers | customer | `customer_id STRING`, `signup_date DATE`, `province_id STRING`, `segment STRING` |
| customer_segments | customer SCD2 version / `(customer_id, valid_from)` | `customer_id STRING`, `segment STRING`, `valid_from DATE`, `valid_to DATE NULLABLE` |
| products | product | `product_id STRING`, `category STRING`, `subcategory STRING`, `base_price NUMERIC(18,2)`, `unit_cogs NUMERIC(18,2)` |
| orders | order | `order_id STRING`, `customer_id STRING`, `order_date DATE`, `province_id STRING`, `status STRING` |
| order_items | order line | `order_item_id STRING`, `order_id STRING`, `product_id STRING`, `quantity INT64`, `unit_price NUMERIC(18,2)`, `discount_pct NUMERIC(8,4)` |
| payments | payment event | `payment_id STRING`, `order_id STRING`, `payment_date DATE`, `amount NUMERIC(18,2)`, `status STRING`, `method STRING` |
| shipments | shipment event | `shipment_id STRING`, `order_id STRING`, `ship_date DATE`, `delivery_date DATE NULLABLE`, `status STRING`, `carrier STRING` |
| returns | return event | `return_id STRING`, `order_item_id STRING`, `return_date DATE`, `refund_amount NUMERIC(18,2)`, `status STRING` |
| inventory | product/date snapshot / `(snapshot_date, product_id)` | `snapshot_date DATE`, `product_id STRING`, `quantity_in_stock INT64`, `reorder_point INT64` |
| weather_daily | province/day / `(province_id, observation_date)` | `province_id STRING`, `observation_date DATE`, `precipitation_mm NUMERIC(12,3) NULLABLE`, `temp_max_c NUMERIC(8,2) NULLABLE`, `source STRING` |

All columns not marked nullable are required in the typed BigQuery table, consistent with the local raw-table DDL. Do not infer enumerated domains or timestamp semantics that are absent from the source contract.

## Validation before upload

The adapter independently rejects null/blank or duplicate primary keys in the selected Parquet rows and computes a canonical typed-value digest before transfer.

`load_validated_snapshot(source, ...)` requires:

1. An active pointer to a complete run with the full configured 11-source map.
2. An explicitly selected source whose manifest states `data_classification=synthetic`, zero rejected rows, a positive row count, and valid source/Parquet SHA-256 values.
3. The manifest Parquet path resolving under the expected local Bronze source-hash directory.
4. Actual Parquet SHA-256, source column order, all-string physical types, and Parquet metadata row count matching the active source manifest.
5. A source schema/primary-key mapping that still matches the local `configs/sources.csv`.

This is integrity/provenance checking, not a cryptographic signature. A user who can rewrite both artifact and manifest can create a different locally consistent snapshot. Source CSV bytes are not uploaded; the CSV digest is retained as provenance.

## Immutable GCS objects

- Before any upload, live bucket metadata's owning project number must match the explicit expected project number, and the BigQuery staging dataset's project must match the explicit project ID. A mismatch fails before object creation.
- Parquet: `bronze/source={source}/sha256={parquet_sha256}/part-000.parquet`
- Portable manifest: `manifests/source={source}/active_run={active_run_id}/manifest.json`
- Each upload uses `if_generation_match=0`. On collision/retry, the adapter reads and hashes the existing bytes. Matching bytes are reused; differing bytes fail closed.
- The portable manifest omits local absolute paths. It records active and source-ingest run IDs, both source and Parquet SHA-256 values, row count, physical/logical schemas, GCS generation, size, and CRC32C.
- GCS CRC32C is an object/transport checksum; it is not compared as though it were SHA-256. The client library checks CRC32C on the upload/download path; the adapter also hashes the bytes locally and on duplicate reads.
- The adapter rechecks generation after the BigQuery load. It does not claim a locked retention policy or WORM storage.

## Typed BigQuery staging

- A strict single-region match is required among the requested location, bucket, and `staging` dataset.
- The local transfer/runtime identity needs bucket metadata access to check live location; Terraform includes bucket-scoped `roles/storage.bucketViewer` (currently Beta) and object read/create grants as applicable. Confirm the Beta role is acceptable in the approved project before apply.
- The raw landing table is created with explicit all-STRING schema and a seven-day expiry. Parquet is loaded from the exact GCS object URI with `CREATE_NEVER`, `WRITE_EMPTY`, and no bad rows. The table description records source hashes, object generation, and its load-job ID.
- A separate typed table is created with explicit required/nullable modes and `NUMERIC` precision/scale. SQL casts blank optional values with `NULLIF(value, '')` before casting. Invalid values fail the cast job.
- Raw reconciliation preserves source strings and distinguishes an empty string from NULL; the typed table's declared nullable casts normalize blank optional values to NULL.
- Adapter runs are batch-scoped tables named from source and active run ID. Provenance and exact schema/value checks for both raw and typed tables make a completed retry read-only; mismatched or incomplete prior tables fail closed. No partial table is deleted automatically.
- The receipt verifies GCS generation, load/cast/metrics/raw-reconciliation/typed-reconciliation job IDs, table rows/schema, primary keys, every raw and typed row value, nullable-field counts, and a parameterized filter count. A single metrics query combines total rows, nullable counts, and the filter count.
- Cast, raw-reconciliation, metrics, and typed-reconciliation queries each cap estimated bytes at 256 MiB. Their job IDs and processed/billed bytes are recorded separately.
- There is no staging-to-Silver merge, checkpoint, Gold publication, CDC, or Cloud Run Job in Week 4.

## Business invariants

Source fact grains remain separate: order line, payment, return, shipment, inventory snapshot, and weather observation. This adapter does not join facts or alter any accepted local metric definition. `fulfilled_sales_proxy` remains a synthetic proxy, not accounting revenue. No cloud Gold table is created from the existing Power BI snapshot.
