# ADR — Streaming CDC

**Status:** Draft before implementation

**Date:** 2026-11-17

**Decision owner:** DataForge Week 8 lane

## Context

I am adding a local CDC exercise to the existing DataForge repository. The source contract in `labs/operational_source/001_init.sql` provides `dataforge_operational.orders`, `payment_events`, and an append-only `change_journal` with `change_seq`; it does not provide the `order_items` or `customers` tables in the Week 8 plan's example topology. I will keep the source code unchanged and test against this real schema in a disposable Compose database.

## Decisions

1. **CDC instead of timestamp polling.** I use PostgreSQL WAL capture because the Week 5 counterexample proves that a strict `source_updated_at > cursor` poll misses a later-arriving event with the same timestamp, while a monotonic `change_seq` cursor finds it. WAL change capture records committed row changes independently of wall-clock equality.
2. **Delivery semantics.** I treat Debezium and Kafka as at-least-once delivery. I make the Delta sink effectively-once by keying MERGE on the order primary key, applying only a newer source LSN, preserving Spark's source checkpoint, and recording idempotent transaction identity for each processed micro-batch. I keep that transaction application ID stable while reusing the checkpoint; if I intentionally reset the checkpoint, I rotate the application ID. I claim exactly-once only at the tested sink-state boundary.
3. **Ordering.** I use the order primary key as the Kafka record key, so one order maps to one partition and its changes retain partition order. I compare source LSNs to reject stale replays. I do not assume global order across keys.
4. **Deletes.** I apply Debezium `op='d'` using the `before` row and key, then ignore the following null-valued tombstone after observing it. Delta removes the current row; older physical files remain in table history until retention/VACUUM policy removes them.
5. **Schema evolution.** I set Avro subject compatibility to BACKWARD. I will show a nullable field flowing through the connector and consumer, then submit an incompatible schema and assert that the registry returns HTTP 409 or 422.
6. **Watermark and state.** I use a 5-minute tumbling event-time window and a 10-minute watermark. I write finalized windows in append mode; events arriving within the watermark affect the result, later events are dropped, and Spark can clear old state. I will capture `numRowsDroppedByWatermark` and state metrics from a real streaming query.
7. **Delta versus Iceberg.** I use Delta because the repository already uses Delta in Week 6 and that lets this lane focus on CDC, replay, ordering, and watermarks. I avoid adding a second table-format runtime to this small local stack.

## Consequences

- Tests and evidence must use the actual source schema and pinned local topology.
- The exact image digests, endpoint contracts, recovery behavior, and limitations will be recorded after the implementation is exercised.
