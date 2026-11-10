# P7.2 source change contract

## Scope and version

- Source identity: `dataforge-operational-v1`
- Event schema version: `1`
- Supported source tables: `orders` and `payment_events`
- Writer contract: one serialized PostgreSQL writer; operational mutation and journal append share one transaction.
- Data classification: deterministic synthetic data only.

## Journal row

| Field | Type / rule |
|---|---|
| `change_seq` | Positive, globally increasing `INT64` primary key; authoritative order and checkpoint |
| `change_id` | Stable unique string, safe to reuse for an exact retry only |
| `source_table` | `orders` or `payment_events` |
| `business_key` | `order_id` for orders; `payment_id` for payment events |
| `operation` | `I`, `U`, or `D` |
| `source_updated_at` | UTC timestamp, source delivery/update time; may be earlier than a newer sequence |
| `business_event_at` | UTC timestamp representing the event's business date/time; corrections can move it backward |
| `schema_version` | Logical integer `1`; unknown versions fail closed. The Parquet wire column is STRING `"1"`. |
| `payload` | Canonical JSON post-image for `I`/`U`; key-only object for `D` |
| `payload_sha256` | SHA-256 over canonical payload bytes |

The journal is append-only. `change_seq` reflects serialized commit order because the simulator takes a PostgreSQL transaction-scoped advisory lock before allocating the sequence, mutating state, and appending the event. Retries that reuse an existing `change_id` with the same payload return the original event; a changed payload under the same ID is rejected.

## Post-image fields

`orders` insert/update payload:

```json
{
  "order_id": "W5O0001",
  "customer_id": "W5C0001",
  "order_date": "2026-10-01",
  "province_id": "VN-HN",
  "status": "delivered",
  "order_net_amount": "125000.00"
}
```

`payment_events` insert/update payload:

```json
{
  "payment_id": "W5P0001",
  "order_id": "W5O0001",
  "payment_date": "2026-10-02",
  "amount": "125000.00",
  "status": "success",
  "method": "bank_transfer"
}
```

Money is represented as a decimal string with exactly two fractional digits, validated as `NUMERIC(18,2)`. No payload field uses binary floating point. Updates are full post-images, not partial patches.

The PostgreSQL journal also stores `source_identity` and an `event_sha256` over the journal event envelope. The Parquet wire row carries the fixed schema fields below; source identity remains in the COMPLETE manifest, and the event digest stays source-side provenance. This keeps the loaded table contract identical in the local producer and Cloud Run consumer.

Delete payloads contain only the stable business key. The Silver representation is a soft tombstone retaining the last valid non-key attributes, sequence, and provenance. An order delete never cascades to payments. A deleted order's Gold row remains visible with `order_is_deleted=true`, zero delivered-sales proxy, successful collections preserved, and null variance. A deleted payment remains as a tombstone and no longer contributes to collections.

## Current-state and metric semantics

- Exactly one current Silver order row per `order_id` and one current Silver payment row per `payment_id`.
- Exactly one Week-5 Gold row per `order_id`.
- Delivered-sales proxy is the order amount for an active delivered order; otherwise zero.
- Collections equal the `NUMERIC` sum of active payment rows with `status='success'`, pre-aggregated by `order_id`.
- Variance is collections minus delivered-sales proxy for active orders. It is null for a tombstoned order because order financial comparability ended; payment rows remain independently auditable.
- A payment whose order key does not exist in Silver fails the quality gate. A payment attached to a tombstoned order is retained and visible.
- These synthetic controls are not accounting-recognized revenue and do not change the P6.2 metric contract.

## Batch and checkpoint semantics

`batch_id = SHA256(source_identity | lower_seq | upper_seq | row_value_sha256)`. The Parquet object's key is content-addressed by its full Parquet SHA-256. A manifest is COMPLETE only after the object has been uploaded with create-only semantics and downloaded/rechecked at its recorded generation.

The deterministic batch builder hashes the UTF-8 bytes of exactly `f"{source_identity}|{lower_seq}|{upper_seq}|{row_value_sha256}"`, with decimal sequence bounds and no spaces or newline. The row-value digest sorts by `change_seq`, serializes each normalized wire event as compact sorted-key UTF-8 JSON, and joins records with LF without a trailing LF. `change_seq` and logical `schema_version` are JSON integers in this digest; UTC timestamp strings use six fractional digits and trailing `Z`; `payload` is compact canonical JSON text.

The Parquet wire schema is `change_seq INT64`, `change_id STRING`, `source_table STRING`, `business_key STRING`, `operation STRING`, `source_updated_at TIMESTAMP(UTC)`, `business_event_at TIMESTAMP(UTC)`, `schema_version STRING`, `payload STRING`, and `payload_sha256 STRING`. `change_seq` is unique and `change_id` is unique within the batch. COMPLETE manifest metadata records actual event minimum/maximum sequence, inclusive extraction bounds, row count, schema, timestamp ranges, row-value digest, Parquet digest/size, and exact GCS generation. A journal range may contain gaps because PostgreSQL sequence allocation is not rolled back; row count is validated independently from bound width.

Normal extraction starts from `checkpoint + 1`, captures a committed upper bound inside one consistent source snapshot, and selects at most `--max-events` in sequence order. Explicit `--from-seq`/`--to-seq` replays or backfills a bounded journal range. A backfill never sets the checkpoint below its existing value. Silver `effective_seq` guards every merge against reverting state when an old batch is replayed.

Timestamp-only cursors are not authoritative. `source_updated_at` and `change_seq` are both recorded; same-timestamp events remain ordered by `change_seq`, and retroactive source timestamps are captured by the journal sequence.
