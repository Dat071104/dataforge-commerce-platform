# ADR — Streaming CDC

**Status:** Implemented locally; T1–T7 runtime validation pending

**Date:** 2026-11-17

**Decision owner:** DataForge Week 8 lane

## Context

I am adding a local CDC exercise to the existing DataForge repository. The source contract in `labs/operational_source/001_init.sql` provides `dataforge_operational.orders`, `payment_events`, and an append-only `change_journal` with `change_seq`; it does not provide the `order_items` or `customers` tables in the Week 8 plan's example topology. I will keep the source code unchanged and test against this real schema in a disposable Compose database.

## Decisions

1. **CDC instead of timestamp polling.** I use PostgreSQL WAL capture because the Week 5 counterexample proves that a strict `source_updated_at > cursor` poll misses a later-arriving event with the same timestamp, while a monotonic `change_seq` cursor finds it. WAL change capture records committed row changes independently of wall-clock equality.
2. **Delivery semantics.** I treat Debezium and Kafka as at-least-once delivery. Silver MERGE keeps the source LSN and transaction order, so replayed or older changes cannot replace newer row state. I key the transaction ledger by Spark's `StreamingQuery.id` and `batchId`; the query ID is stable when I restart from the same checkpoint and changes for a new checkpoint. The ledger is a replay optimization and is not atomic with the MERGE. This lab does not claim exactly-once processing; I will claim replay-safe sink state only after T2 and T3 pass.
3. **Ordering.** I use the order primary key as the Kafka record key, so one order maps to one partition and its changes retain partition order. I compare source LSNs to reject stale replays. I do not assume global order across keys.
4. **Deletes.** I apply Debezium `op='d'` using the `before` row and key, then ignore the following null-valued tombstone. Silver retains a soft-delete row with `is_deleted=true` and its source LSN, which prevents an older replay from resurrecting the order. A Spark view filters deleted rows from current-state readers.
5. **Schema evolution.** I set Avro subject compatibility to BACKWARD. I will show a nullable field flowing through the connector and consumer, then submit an incompatible schema and assert that the registry returns HTTP 409 or 422.
6. **Watermark and state.** I use Debezium `source.ts_ms` as the event time, not the envelope processing timestamp or the source row's business `event_time`. The gold pipeline deduplicates order changes by `(order_id, source_lsn, transaction_order)` within a 10-minute watermark, expands update/delete before-images into negative revenue legs and after-images into positive legs, then recomputes affected 5-minute windows. A Delta change ledger makes those legs replay-safe, and a `foreachBatch` MERGE replaces totals by `(window, province)`. T5 must confirm within-watermark updates, late-row drops, and progress metrics before I claim the behavior is validated.
7. **Delta versus Iceberg.** I use Delta because the repository already uses Delta in Week 6 and that lets this lane focus on CDC, replay, ordering, and watermarks. I avoid adding a second table-format runtime to this small local stack.

## Consequences

- Tests and evidence must use the actual source schema and pinned local topology.
- The exact image digests, endpoint contracts, recovery behavior, and limitations will be recorded after the implementation is exercised.
