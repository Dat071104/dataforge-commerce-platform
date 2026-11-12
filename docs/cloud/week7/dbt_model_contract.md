# Week-7 dbt model contract

**Scope:** the deterministic Week-5 operational simulator's current state only. The Week-4 eleven-stream snapshot, all local PostgreSQL marts, and the Week-5 Silver/Gold publisher remain authoritative for their existing workloads.

## Sources and grains

| dbt relation | Source | Grain | Contract |
|---|---|---|---|
| `stg_week5_orders` | `silver.week5_orders` | one current row per `order_id` | Typed current post-image, `effective_seq`, provenance, and `is_deleted`; keep soft tombstones. |
| `stg_week5_payment_events` | `silver.week5_payment_events` | one current row per `payment_id` | Typed current payment post-image, `effective_seq`, provenance, and tombstone state. |
| `stg_week5_pipeline_checkpoints` | `ops.pipeline_checkpoints` | one row per `source_id` | Committed normal journal sequence and immutable last-batch metadata. |
| `stg_week5_run_events` | `ops.week5_run_events` | one row per event | Week-5 attempts and statuses used for batch lineage and quality gates. |
| `int_week7_batch_control` | run events + checkpoint | one row per Week-5 `run_id` | Summarizes validated/staged/checked/published/failed outcomes; a normal run must include a checked publication whose checkpoint reaches its upper sequence. A backfill is allowed to leave the normal checkpoint unchanged. |

The simulator only contains `orders` and `payment_events`. The project does not infer customers/products/shipments/returns or pretend it contains all Week-4 commerce streams.

## Business models

| Model | Grain | Definition |
|---|---|---|
| `int_week5_active_orders` | one nondeleted order | Current active order attributes; retained alongside the all-orders control path for relationship checks. |
| `int_week5_current_payments` | one payment event | Current payment state, including tombstones. |
| `int_week5_payment_control_by_order` | one order with payment activity | Pre-aggregates active payment counts, successful payment counts, amount, and maximum payment sequence before joining to orders. |
| `int_week5_successful_collections_by_order` | one order with successful payments | Sum of active `payment_status='success'` amounts using BigQuery `NUMERIC`; tombstoned and failed payments do not contribute. |
| `int_week5_delivered_sales_proxy_by_order` | one order | `order_net_amount` only for active delivered orders; zero otherwise. This is not accounting-recognized revenue. |
| `fct_week7_order_reconciliation` | one current row per `order_id` | Combines delivered-sales proxy and independently aggregated payments. Deleted orders remain present, keep successful collections visible, have zero delivered-sales proxy, and null variance. |
| `fct_week7_build_receipt` | one row per `workflow_run_id` | Captures manifest, run mode, current source checkpoint, candidate row count, and deterministic checksum. |

The candidate is tested against the accepted `gold.week5_order_controls` table on the same current source snapshot. Active payment relationships exclude tombstones; a tombstoned order is not dropped.

The public `gold_week7.published_order_reconciliation` view returns rows only while the singleton pointer's `publication_is_current` flag is true. Lock acquisition clears that flag before Week 5 can advance Silver; a failed dbt build or reconciliation leaves the public view empty. The successful pointer transaction sets the new version and the flag to true atomically. Consumers should treat an empty public view as “no verified current publication”; historical immutable versions remain available in the explicitly named version table for audit.

## Incremental correctness

`fct_week7_order_reconciliation` uses BigQuery `MERGE` with `order_id` as the unique key. A stable 0–63 integer-range partition derives only from `FARM_FINGERPRINT(order_id)`, and the merge predicate compares the same bucket on source and target. Business-date corrections therefore cannot move an existing key to another partition. The model recomputes an order when its current order sequence changes, a new order appears, or the maximum effective payment sequence for that order changes. Payment tombstones remain in that sequence watermark, preventing a deleted payment from being silently forgotten. Moving a payment to another order changes both affected aggregates.

An unchanged replay emits no candidate rows and leaves existing incremental rows intact. A quality-gate failure likewise emits no changed rows; dbt's required data tests then fail the build, so the Workflows subflow never calls publication. Full-refresh comparison runs into `dbt_week7_full`; that dataset is never published.

The effective source cursor is the monotonically increasing Week-5 `effective_seq`, not business event time or ingestion time. Late business-date corrections receive a later sequence and are included. The normal checkpoint and manifest upper sequence are recorded separately. A checked backfill may update current state without advancing the normal checkpoint; later normal processing of a wider range is replay-safe because the Week-5 publisher accepts identical effective-sequence identities.

## History and limitations

`week5_orders_history` is a dbt timestamp snapshot of states observed at dbt snapshot execution time, using Silver `ingested_at` as `updated_at`. It proves SCD2 mechanics for the synthetic simulator but cannot reconstruct source history that predates the first snapshot or multiple changes coalesced between snapshot runs. Its validity interval is observation history, not business-effective time.

Partitioning and clustering are design choices whose actual pruning and billed bytes are recorded only from live BigQuery receipts. The dataset is four/five-row educational control data; no scale or cost optimization claim follows from it.
