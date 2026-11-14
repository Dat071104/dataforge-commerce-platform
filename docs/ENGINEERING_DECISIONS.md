# Engineering decisions

AUTHOR REVIEW REQUIRED

This is an AI-assisted first-person draft assembled from repository files and retained CI or receipt evidence. The author must review the wording before presenting it as personal reflection. This document is not mentor approval, an independent review, or a course-completion record.

## Decisions I can defend from the repository

### 1. I keep the four workloads separate

I keep the synthetic commerce baseline, the Week 4–7 GCP exercises, the local NYC taxi Spark lab, and Mini3 weather as separate domains. Their grains, operators, and cleanup rules differ. This keeps weather observations out of commerce facts and keeps the local benchmark distinct from a managed cluster.

Evidence: [baseline architecture](architecture.md), [domain diagram](diagrams/architecture.mmd), and [Week 7 architecture and tradeoffs](demo/week7_checkpoint/architecture_and_tradeoffs.md).

### 2. I preserve the local commerce model as a reference point

I keep order items, payments, returns, and shipments at separate fact grains and define proxy metrics with explicit caveats. A join across those facts can multiply amounts, so order reconciliation aggregates each source grain before combining it. Fulfilled sales is not accounting revenue.

Evidence: [metric contract](metric_contract.md), [SQL mart build](../sql/build/010_marts.sql), and [P6.2 local release record](releases/v1.0-local.md).

### 3. I make file identity explicit before loading data

For the local baseline, I use content-addressed Parquet files and an atomic active-manifest pointer. For cloud objects, receipts retain the object generation and content hash. These values help detect changed or missing bytes and make replay requests identifiable; they are integrity checks, not signatures against an actor who can rewrite both the object and manifest.

Evidence: [local ingestion architecture](architecture.md), [Week 4 acceptance](cloud/week4_acceptance.md), and [Mini3 API-to-Gold receipt](cloud/week7/closure/api_to_gold_e2e_receipt.json).

### 4. I use sequence order for the Week 5 journal

I use the transactionally allocated change_seq as the journal cursor. A timestamp alone can miss a later event with the same updated_at value. The learning test demonstrates that counterexample and that a strictly newer sequence recovers the event; Lane D remains an unmerged feature branch.

Evidence: [Week 5 source](../src/dataforge/incremental/source.py), [Week 5 batch runtime](../src/dataforge/incremental/batch.py), and [Lane D cursor test](https://github.com/Dat071104/dataforge-commerce-platform/blob/a7fe5b93f1b4cec2f1e70e7b39551a97f87b5b8f/tests/learning/test_change_cursor_counterexample.py).

### 5. I preserve source grains and aggregate before joining

I keep item, payment-event, return, and shipment measures at their own grain. Where a report needs an order-level comparison, SQL aggregates each side first. This is more explicit than one wide join and makes fan-out and date-role choices visible.

Evidence: [metric contract](metric_contract.md), [Week 5 report](cloud/week5/final_report.md), and [Week 7 model contract](cloud/week7/dbt_model_contract.md).

### 6. I publish Gold through a tested boundary

I build a candidate, validate it against tests and a reconciliation oracle, and only then move the current pointer. A failed candidate should not become the published version. The Week 5/7 receipts show this for the synthetic commerce simulator; Mini3 weather has a separate pointer and only a one-date, three-province observation.

Evidence: [Week 7 acceptance matrix](cloud/week7/acceptance_matrix.md), [publication macro](../dbt/dataforge/macros/week7_publication.sql), and [Mini3 receipt](cloud/week7/closure/api_to_gold_e2e_receipt.json).

### 7. I keep finite cloud jobs separate from scheduler ownership

For bounded cloud tasks, Workflows calls finite Cloud Run Jobs. Airflow is a separate orchestration implementation. The merged Week 7 Airflow code passed Airflow 3.4 in a no-egress scheduler harness; it did not create a hosted scheduler or a recurring daily run.

Evidence: [Airflow DAG](../labs/airflow_reference/dags/dataforge_week7_weather_cloud.py), [P7.5 Airflow closure](cloud/week7/closure/p75_airflow_correctness.md), and [PR #11 checks](https://github.com/Dat071104/dataforge-commerce-platform/pull/11/checks).

### 8. I fail terminal work fast and bound each wait

The earlier combined sensor used reschedule mode, but it ran after a synchronous Cloud Run wait and did not demonstrate a useful asynchronous wait. P7.5 removed that redundant sensor; the revised task owns a bounded operation poll and fails HTTP 403, terminal execution, identity, and receipt errors without retry. The no-egress scheduler harness checks retry, forbidden, gate-off, failure, deadline, and backfill scenarios. One deadline attempt failed; an unchanged same-head rerun passed, and no assertion was weakened. A later combined-head Lane B run exposed a separate deadline state mismatch that remained open at the Lane E checklist snapshot.

Evidence: [P7.5 Airflow closure](cloud/week7/closure/p75_airflow_correctness.md), [Week 7 CI rerun](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43562629089), [PR #11 Airflow job](https://github.com/Dat071104/dataforge-commerce-platform/actions/runs/43567547422/job/132364562675), and the Lane B status in the [evidence index](EVIDENCE_INDEX.md).

### 9. I describe retry as at-least-once submission with idempotent effects

Cloud Run does not accept the caller-provided idempotency token needed to guarantee one submission after an ambiguous timeout. The pipeline reuses a stable invocation identity and relies on immutable writes, exact-generation receipts, merge semantics, and publication checks to control data effects. I do not claim exactly-once execution or exactly-once API requests.

Evidence: [Mini3 API contract](cloud/week7/closure/mini3_api_contract.md), [Airflow failure contract](cloud/week7/closure/p75_airflow_correctness.md), and [Week 7 recovery report](cloud/week7/failure_recovery.md).

### 10. I use keyless identities and keep live permissions explicit

The design uses workload identity or attached identities and does not include a service-account key. I did not add IAM bindings in Lane C. The current gcloud token could not be refreshed, so current VM and effective Artifact Registry permissions remain unverified; the C4 apply is still blocked.

Evidence: [IAM matrix](cloud/iam_matrix.md), [Week 7 security notes](cloud/week7/security_iam.md), and [Lane C report](process/lanes/c.md).

### 11. I keep measured negative results

The local Spark benchmark processed 13.07 million rows. The broadcast candidate moved fewer shuffle and spill bytes but was 19.8% slower by median on this constrained host. I keep that result instead of describing the optimization as a speedup.

Evidence: [Week 6 benchmark](cloud/week6/benchmark.md) and [final report](cloud/week6/final_report.md).

### 12. I require a complete cost bound before starting paid cloud work

The planned C4 fixed subtotal is USD 4.985947 for 120 hours, about USD 0.04155/hour, before NAT processing, egress, logging, and staging. That is a lower bound, not a worst-case estimate. C7 compute plus illustrative shuffle is USD 0.720548, but GCS and network costs are still unbounded. No VM or managed Spark batch was created by this phase, and the settled project bill is unknown.

Evidence: [Lane C cost and blocker report](process/lanes/c.md), [Week 7 operations notes](cloud/week7/ops/README.md), and the local D-pack checklist, which is not versioned in this repository.

## AUTHOR REVIEW

Author review is pending. Confirm that the first-person wording accurately reflects the author's decisions and revise any statement that does not.
