# P7.4 / Week 7 — architecture and decisions

**Status:** bounded live implementation and acceptance complete; independent controller returned `CLOUD_GO_WEEK7`; PR [#5](https://github.com/Dat071104/dataforge-commerce-platform/pull/5) was created in Chrome after the GitHub app API returned 403, and exact-head PR checks passed. The linked PR is the merge record. All cloud claims are tied to the dated receipts under `docs/cloud/week7/`.

## Accepted baseline and ownership

The repository has three separate accepted paths. Week 4 loaded synthetic snapshot extracts into GCS Bronze and BigQuery staging. Week 5 uses its own local operational-source journal, immutable GCS manifests, a finite Cloud Run consumer, and BigQuery `MERGE`s. Week 6 is a separate local NYC Taxi Spark lab and has no dependency on the commerce cloud tables.

Week 5 is the only source for this Week-7 dbt exercise. Its current-state Silver tables are `silver.week5_orders` and `silver.week5_payment_events`. They contain the latest post-image per business key, including soft tombstones and monotonic `effective_seq`; they are authoritative for this narrow operational simulator. `ops.pipeline_checkpoints` is authoritative for the committed journal sequence. `ops.week5_run_events` is the immutable-by-convention operational history (the existing IAM principal technically has dataset-level edit rights). `gold.week5_order_controls` is the accepted Week-5 per-order control output. Week 7 does not rewrite that table, its checkpoint, or the Week-4 eleven-stream snapshot tables.

The Week-5 simulator represents only orders and payment events. It does not contain all eleven Week-4 commerce source streams, so the Week-7 models and all claims are restricted to this operational slice.

## Week-7 model boundary

The dbt project reads Week-5 Silver and operational metadata as sources. It exposes typed staging views, then independently models current orders, current payment events, successful collections per order, delivered-sales proxy per order, reconciliation controls, and batch quality/control summaries. Order and payment grains remain distinct until each is aggregated to order grain. A payment attached to a missing order fails a relationship/reconciliation gate; a payment attached to a tombstoned order remains auditable. A tombstoned order remains present, has zero delivered-sales proxy, preserves its active successful collections, and has null collection variance.

Week-5 `gold.week5_order_controls` remains the compatibility reference for the same source snapshot. Week-7 incremental candidates are built in isolated `dbt_week7`; the independent full-refresh comparison is built in `dbt_week7_full`. After dbt build, data tests, and reconciliation all succeed, a separate publication step appends an immutable run version under `gold_week7` and atomically advances `gold_week7.week7_publication_pointer`. The pointer records manifest sequence, actual committed source checkpoint, run mode, candidate row count, checksum, and `publication_is_current`. A validated backfill may have `upper_seq` above the normal checkpoint; it never advances that checkpoint, and the two values remain distinct in the receipt. Lease acquisition clears `publication_is_current`; the public view filters to true and returns no rows while Silver is ahead or validation is incomplete. The publication transaction advances the pointer and restores the flag to true together. Historical immutable versions remain available for audit, but a failed candidate is not advertised as current.

## Orchestration and batch selection

The developer's PostgreSQL is on `127.0.0.1` and is unreachable from GCP. Local extraction/upload remains an explicit source bridge. The cloud workflow accepts either a complete manifest URI plus its exact GCS generation, or an explicit `NO_NEW_BATCH`. It never scans a local laptop, infers a mutable "latest" object, or claims ingestion when no manifest was supplied. For a manifest, the workflow verifies the immutable-generation contract, acquires the BigQuery publication lease, then invokes the existing Week-5 Cloud Run Job and waits for its terminal execution result before launching dbt. Holding the lease across Week-5 and dbt prevents another batch from advancing Silver during a candidate build. Week-5 itself advances its journal checkpoint only after its transaction checks pass.

The Cloud Scheduler job is optional and disabled in Terraform by default. After the manual Workflows path and recovery drill pass, the job is created paused with a fixed `NO_NEW_BATCH` body and can be force-run once for a trigger-path receipt. A paused Scheduler job can still accrue a per-job monthly charge, so the Week-7 demo job is removed after that receipt unless recurring execution is separately accepted. The schedule is never resumed in this phase and is not described as an unattended source feed. Workflows orders each execution's calls, but does not itself serialize distinct executions. A BigQuery-backed compare-and-set lease in `ops.week7_publish_lock` guards the Week-5 checkpoint advancement and Week-7 candidate build/publication. The transaction advances `gold_week7.week7_publication_pointer` only if the expected prior `pointer_version` still matches. Per-run state and outcomes are written to `ops.week7_publish_events`. If a lease cannot be acquired, the second execution exits with `OVERLAP_SKIPPED`; it does not execute a second publication.

## Failure and recovery behavior

If Week-5 Silver succeeds but dbt fails, the Week-5 checkpoint remains committed and the prior Week-7 publication pointer remains unchanged. Recovery reuses the same manifest identity: the Week-5 consumer returns its verified replay/no-op result, then dbt rebuilds/verifies the candidate and publishes only after checks pass. If the Gold quality gate fails, the workflow fails visibly and does not advance the pointer. If a publication copy succeeds but the pointer update fails, the unreferenced immutable version is retained for audit and a retry can safely reuse its deterministic run/version ID.

The workflow uses bounded retries for transient execution/transport failures only. Invalid/incomplete manifests, digest or generation mismatch, schema drift, IAM errors, dbt data-test failures, and reconciliation failures are terminal until corrected. Structured logs carry `run_id`, `batch_id`, attempted step, status, and error code, with no credentials or customer secrets.

## IAM, cost, and environment

The target is the isolated synthetic project `dataforge-p7-lab-d0f725` (`955038620072`) in `us-central1`, with private Bronze bucket `dataforge-p7-lab-d0f725-bronze`. The Week-5 runtime account and accepted datasets stay in place. Week 7 adds separate workflow, dbt runtime, Scheduler, and read-only CI identities; runtime grants are scoped to the resources and jobs each identity needs. No service-account key is used. The workflow is authorized to execute only the required Cloud Run Jobs. Scheduler can create workflow executions only. The dbt runtime can run BigQuery jobs, read Week-5 Silver/ops sources, and write only Week-7 candidate/published outputs. GitHub OIDC is constrained to repository ID `1446796465`, owner ID `242334093`, and direct pushes on `main` or `feature/p7-*`; pull-request and fork events are rejected by the provider. The CI identity has BigQuery job-user plus dataset metadata-read roles only, with no table data or write permissions and no Cloud Run/IAM deployment roles.

The user's gross spend target is below USD 5 for the bounded Week-7 demonstration, not a cap. Every dbt BigQuery query has a maximum-bytes-billed limit; Cloud Run uses one task, one retry at most, a short timeout, and bounded CPU/memory. There is no Composer, VM, Cloud SQL, GKE, public bucket, or enabled recurring schedule. Before any apply or run, the exact gcloud/ADC project, Terraform workspace, plan delta, APIs, principals, and available cost evidence must be reviewed. Stop if the project/identity differs, if the plan changes or destroys an accepted Week-4/5 resource, if a query exceeds its cap, or if the projected gross task cost exceeds USD 5.

Billing data is delayed and previous receipts explicitly leave the settled project charge unknown. The plan's threshold is therefore an operational forecast, not a billing guarantee. No billing upgrade or billing-configuration change is in scope.

## Simplified flow

```text
local operational journal
  -> immutable GCS manifest (URI + generation supplied explicitly)
  -> Workflows (verify -> Week-5 job -> terminal status)
  -> Week-5 BigQuery Silver + committed sequence
  -> finite dbt Cloud Run Job (candidate models + tests + reconciliation)
  -> immutable Week-7 Gold run version
  -> compare-and-set publication pointer
  -> published Gold view

Cloud Scheduler (disabled; safe NO_NEW_BATCH body) -> Workflows
Local Airflow DAG -> same logical stages, fixture-only by default
```

## Official implementation references

- [dbt incremental models](https://docs.getdbt.com/docs/build/incremental-models) and [BigQuery incremental configuration](https://docs.getdbt.com/reference/resource-configs/bigquery-configs)
- [dbt BigQuery setup, ADC identity, and maximum bytes billed](https://docs.getdbt.com/docs/local/connect-data-platform/bigquery-setup)
- [Cloud Run Jobs executed with Workflows](https://docs.cloud.google.com/workflows/docs/tutorials/execute-cloud-run-jobs)
- [Apache Airflow DAG testing](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/debug.html)
