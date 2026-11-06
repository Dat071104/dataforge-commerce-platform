---
name: dataforge-kimball
description: Design or review DataForge PostgreSQL Kimball star schemas, fact grain, SCD2, metric reconciliation and analytical SQL performance.
---

# Dimensional warehouse workflow

1. Read `docs/architecture.md`, `docs/metric_contract.md`, schema/mart SQL. Write explicit fact grain table before joins.
2. Distinguish source facts (orders, order items, payments, returns, shipments, inventory snapshots); never join unrelated row-level facts before aggregation.
3. SCD2 start-inclusive, end-exclusive, no overlaps; no synthetic history disguised as real observations.
4. Use numeric currencies; define which statuses qualify for each metric and which event date governs it.
5. Add SQL assertions for referential integrity, cardinality, metric reconciliation and failed assumptions.
6. Benchmark with actual EXPLAIN ANALYZE and equivalently measured baseline after realistic row counts; no invented speedup.
7. Non-goal: build Data Vault, Kafka, Spark or an enterprise semantic layer during Week 3.
