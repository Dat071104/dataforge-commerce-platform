# Week 8 — Streaming CDC

**Scope:** local Docker Compose and GitHub Actions only. This lane is built in `feat/w8-cdc-streaming`; it does not write to GCP or a hosted service.

The operational source in this repository is `dataforge_operational.orders` and `dataforge_operational.payment_events`, with an append-only `dataforge_operational.change_journal`. The source has no `order_items` or `customers` tables, so this lab uses the tables that exist. The stream uses `orders` as the silver CDC target and `orders` changes for the revenue window.

## Runtime versions

| Component | Selected version | Notes |
|---|---:|---|
| PostgreSQL | 16.16 (Alpine 3.23) | Same major as the operational source lab; logical WAL enabled. Image digest will be recorded in Compose before stack build. |
| Kafka / KRaft | Confluent Platform 7.9.11 (Kafka 3.9.x) | Single local broker, three partitions per CDC topic, RF=1. |
| Schema Registry | Confluent Platform 7.9.11 | Avro, BACKWARD subject compatibility. |
| Kafka Connect / Debezium | Debezium 3.1.3.Final | Built against Kafka Connect 3.9.0; Confluent Avro converter artifacts match CP 7.9.11. |
| Spark | 3.5.9 | Reuses the Week 6 Spark baseline. |
| Delta Lake | 3.3.3 | Reuses the Week 6 Delta baseline; compatible with Spark 3.5.x. |
| Spark Avro | `org.apache.spark:spark-avro_2.12:3.5.9` | Decodes the Confluent Avro payload after its 5-byte wire header is removed. |
| Spark Kafka source | `org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.9` | Structured Streaming Kafka source. |

**Image pinning:** every published image reference in Compose will use a version tag and immutable digest. Locally built Connect/Spark images will use pinned digest bases and versioned, checksum-verified dependencies. Digests are finalized before 8.2 stack build.

## Run locally

The three-command run sequence and readiness checks will be finalized after T1–T7 pass.

## Diagram

The Mermaid diagram will be finalized with the actual service and sink topology after integration tests pass.

## Production mapping

Production alternatives and trade-offs will be finalized after the local behavior is proven.
