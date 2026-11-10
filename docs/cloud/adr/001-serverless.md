# ADR-001 — Serverless batch instead of always-on infrastructure

**Status:** Accepted for synthetic Week-4 foundation. The isolated foundation, 11 first-pass transfers, 11 safe reruns, and runtime IAM checks are live and passed. Measured usage is recorded in [the cost receipt](../cloud_cost_receipt.md); billing settlement remains unverified and the independent final controller returned CLOUD_GO_WEEK4.

## Context

The accepted v1.0-local path remains Python → content-addressed Parquet → local PostgreSQL → Kimball marts → Power BI Desktop. PostgreSQL remains bound to the developer machine; a cloud runtime cannot reach its loopback address. The cloud handoff begins after a local validated Parquet artifact and portable manifest are available.

The current GCP target is the new project `dataforge-p7-lab-d0f725` in `us-central1`. The previous shared-project target was superseded before apply; its SaigonBite resources were not changed. The new project is linked to the existing active Free Trial, with no billing upgrade.

## Decision

- Use one private regional GCS bucket for immutable-by-adapter Bronze Parquet and manifests. Uploads use create-only generation preconditions and verify bytes/generation; the bucket does not have locked WORM retention.
- Use native BigQuery datasets `staging`, `silver`, and `gold` in the same region. Week 4 writes raw and explicitly typed tables only to disposable `staging` tables.
- Keep a keyless runtime service account with GCS object read, project BigQuery job execution, and `staging`-dataset table write. No Silver or Gold access is granted.
- Keep a service-account-scoped Token Creator grant for the verified operator to reproduce keyless runtime identity checks. It is limited to `dataforge-runtime`; no service-account key or project-wide Token Creator grant exists.
- Consider a finite Cloud Run Job only in Week 5, after incremental semantics and the Week-4 acceptance review. It is not deployed here.
- Do not add a VM, NAT, Cloud SQL, GKE, Composer, or an always-on service for this workload.

## Week-4 evidence

All 11 synthetic sources passed first transfer: 16,259 rows and 235,910 Parquet bytes. All 11 safe replays reused matching objects and raw/typed tables; row counts, source/Parquet hashes, object generations, and exact values matched. Runtime GCS read and BigQuery query succeeded; anonymous object access and runtime Gold listing were denied. Details are in the [deployment scope review](../deployment_scope_review.md), [transfer receipts](../evidence/transfers/), [rerun receipts](../evidence/reruns/), and [IAM verification](../evidence/iam_live_verification.json).

## Cost and trade-offs

Finite execution avoids idle compute, but it does not make the lab free. GCS storage and operations, BigQuery storage and query bytes, logging, and network transfer can accrue charges. The operational target is **USD 10**, not a quote or hard cap. The project is linked to the existing active Free Trial; a usage-based receipt from actual job bytes and current pricing is still being prepared. Do not infer settled spend or publish personal credit details.

The local adapter caps each BigQuery query at 256 MiB processed and gives staging tables a seven-day expiration. These are safeguards, not billing guarantees.

## Consequences and remaining work

- The local laptop remains the source bridge. If it is offline, the cloud cannot discover new local batches.
- There is no staging-to-Silver merge, checkpoint, Gold publication, CDC, or Cloud Run Job in Week 4.
- The Owner performing deployment is privileged; the runtime service account is separate and scoped to the Week-4 data boundary.
- No independent final controller verdict has been issued yet. Cost reconciliation and final acceptance remain open.

## References

- [BigQuery pricing](https://cloud.google.com/bigquery/pricing)
- [Cloud Storage pricing](https://cloud.google.com/storage/pricing)
- [BigQuery batch loading](https://docs.cloud.google.com/bigquery/docs/batch-loading-data)
