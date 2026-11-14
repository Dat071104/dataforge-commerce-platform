# Architecture and trade-offs

## Objective and scope

DataForge demonstrates bounded ingestion, typed contracts, dimensional modeling, recovery, testing, and evidence. Four workloads have separate grains and lifecycles:

| Domain | Implemented path | Boundary |
|---|---|---|
| Local commerce | Synthetic CSV → Python validation → content-addressed Parquet and manifest → PostgreSQL raw/audit → Kimball marts → SQL/Power BI | Local reference baseline; proxy metrics are not accounting revenue. |
| Week 4 cloud snapshot | Synthetic source extracts → private GCS Bronze → BigQuery raw and typed staging | Bounded historical transfer and validation evidence. Current resource inventory is not asserted here. |
| Week 5/7 commerce | Separate PostgreSQL change journal → immutable GCS manifest → Cloud Run consumer → BigQuery Silver/checkpoint → dbt candidate/reconciliation → versioned Gold pointer | Reads a small deterministic simulator; it does not transform every Week 4 source stream. |
| Week 6 Spark | Public NYC TLC files → local Docker/PySpark → quality ledger and hourly/zone aggregates → partitioned Parquet plus a local Delta example | Managed Spark was not run. |
| Mini3 weather | Open-Meteo ERA5 → finite Cloud Run ingest → immutable weather Bronze → BigQuery landing → isolated dbt models → weather Gold versions/pointer | One settled observation date and three locations; separate from commerce facts. |

The GCP substitution for Azure/Fabric is recorded as user-reported mentor approval, without a separate written approval artifact. The mapping describes learning analogies and differences, not service equivalence.

## Correctness and publication

The local commerce model keeps order items, payment events, returns, and shipments at their own grain. The Week 5 journal uses a transactionally allocated change_seq cursor. Manifests, content hashes, and immutable object generations help detect replays and changed bytes; they are not signatures against an actor who can rewrite the object and manifest.

Week 7 dbt builds and checks a candidate before the publication step. A currentness fence leaves the public Gold view empty if publication is not verified. Weather Mini3 has separate tables, models, and a separate pointer. Its one-date receipt is not a long-history analytics mart.

## Orchestration evidence and limits

Cloud Workflows invokes finite Cloud Run Jobs. Airflow is a separate orchestration implementation, not a hosted service:

- The historical integration receipt records one Airflow 3.4 run in local Docker against the GCP data plane. In that earlier implementation, the task synchronously waited for Cloud Run; the later receipt sensor therefore did not provide a genuine asynchronous wait.
- P7.5 removed that redundant sensor and separates cloud authorization from the requested run mode. Its no-egress scheduler harness tests task retry, deadline, forbidden, gate-off, failure, and backfill behavior using fake authorized I/O. It does not prove a live GCP retry or an external notification.
- B PR #9 merged at 9bca18c and D PR #13 merged normally at f4d340ff151557040d85e1688a9e0f94caa2a8c5. D exact-head checks passed with one expected keyless-compile skip; Airflow job 132422133934 passed all six scenarios on attempt 2. Attempt 1 timed out on the fifth synthetic backfill date. The exact failed task state/root cause was not captured; no code/assertion changed between attempts, and the retry budget is exhausted.
- Merge-SHA base CI 43606510616 and Week 7 CI 43606510673 passed on f4d340f. Airflow job 132482197676 succeeded and artifact 14118655954 (SHA-256 9a0a8d20c7f1599a8b4d722a81b8eefa84abd3bf9eea7b89cb412a87c7068d52) was uploaded. This green merge check does not explain the earlier backfill timeout or prove live GCP retry.
- No recurring Airflow schedule is active, Airflow is not hosted on GCP, and no current external notification channel is claimed.

The cost and cleanup receipts record one historical Scheduler firing and one controlled notification; both temporary resources were removed after their demonstrations.

## Security and operations

The design uses project/resource allowlists, keyless identities, scoped service accounts, immutable inputs, and bounded queries where recorded. No static service-account key was created in the retained evidence. Current effective IAM and VM inventory were not rechecked in Lane E because the D-pack checklist records an H5/R1 reauthentication and inventory blocker. No GCP resource is confirmed running, but the unavailable inventory does not prove that none exists; actual hourly run-rate remains unknown.

Retries may resubmit a Cloud Run job after an ambiguous transport timeout. Stable invocation identity, immutable writes, content hashes, MERGE semantics, and publication checks control data effects, but do not guarantee exactly-once API submission or exactly-once provider requests.

## Cost evidence and limits

See the [cost table](cost_table.md) and [historical Week 7 cost and cleanup report](../../cloud/week7/closure/iam_cost_cleanup.md). The approximately USD 0.095 Cloud Run plus BigQuery amount is a gross usage-based list-price estimate, not settled billing. The total billed project spend is unknown. Planned C4 and C7 figures exclude variable or unbounded items and are not actual charges. No Lane D/E GCP action occurred; existing cloud resources were not inventoried live for this report.

No budget alert is claimed as currently configured. A budget alert is informational and is not a hard spending cap. Managed Spark, hosted Airflow, a persistent notification channel, and Weeks 8–12 are not completed claims.

## Presentation decision

Present the static artifacts and ask the mentor whether the hybrid local-Airflow/GCP-data-plane evidence satisfies the Week 7 checkpoint. If the mentor requires hosted Airflow, managed Spark, a recurring alert, or a budget resource, obtain a separate, concrete authorization with target, permissions, duration, cost bound, evidence objective, and teardown before any cloud write.
