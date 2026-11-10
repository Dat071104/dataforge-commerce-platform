# IAM, cost, and cleanup audit

## Project and data boundary

All Week-5 cloud work used only `dataforge-p7-lab-d0f725` (project number `955038620072`) in `us-central1` and its existing private Bronze bucket. The live bucket has public access prevention **enforced**, uniform bucket-level access **enabled**, a 30-day lifecycle rule for `tmp/`, and a seven-day soft-delete window. No public service, alternate project, or billing API was enabled.

## Runtime IAM

The keyless `dataforge-runtime` service account has:

- Project roles: `roles/bigquery.jobUser` and `roles/serviceusage.serviceUsageConsumer` only.
- Bronze bucket roles: `roles/storage.objectViewer` and `roles/storage.bucketViewer`; no object create/delete role.
- Dataset `WRITER` entries (BigQuery `roles/bigquery.dataEditor`) on `staging`, `silver`, `gold`, and `ops`.
- No project Owner or Editor role and no service-account key.

The live IAM negative probe attempted object creation in the approved bucket and received the expected HTTP 403, recorded as `IAM_NEGATIVE_PASS` for both attempts in two executions. No probe object was created. Exact role inventory and run receipts are preserved in `batch_run_ledger.json` and `cloud_run_executions.json`.

The short-lived OAuth refresh expired during benchmark work. The user completed the standard Google Cloud SDK sign-in in the existing School Chrome profile; the isolated project configuration then minted a short-lived token successfully. Reauthentication changed no service-account, project-IAM, or billing permissions, and no access token was placed in the repository.

**Residual scope:** BigQuery dataset-level `WRITER` lets the service account mutate tables across each of those four datasets. BigQuery IAM cannot make the `ops.week5_run_events` table append-only for this principal. The runtime SQL writes expected inserts/transactions, but direct misuse of the same identity could update or delete rows. For production, split loading from publishing and narrow table-level permissions where supported. The pre-existing Token Creator binding for the Week-4 runtime identity smoke test was retained on the single runtime service account because it is part of the approved state; no other identity or project role was added.

## Gross list-price estimate

The BigQuery inventory captured parent and child jobs from the target project’s last seven days. Parent script totals equal their children; the estimate sums **top-level** `total_bytes_billed` once and does not add child bytes again. The final inventory contains 6,027,214,848 billed bytes across Week-5 top-level jobs. Its own final metadata query billed another 20,971,520 bytes, for 6,048,186,368 bytes in the gross estimate.

| Service | Observed usage | Gross on-demand/list estimate |
| --- | ---: | ---: |
| BigQuery analysis | 6,048,186,368 billed bytes, including the final job-inventory query | $0.0344 at $6.25/TiB |
| Cloud Run Jobs | 16 executions; 2,229 task seconds total; 1 vCPU and 0.5 GiB | $0.0401 CPU + $0.0022 memory |
| **Measured compute subtotal** | BigQuery + Cloud Run | **$0.0767** |
| Artifact Registry/GCS/storage | Small synthetic artifacts; some immutable image storage remains | Not fully metered in this estimate |

The benchmark’s three query jobs billed 218,103,808 bytes in total (about $0.00124 at gross list price) and are included in the BigQuery total above. The estimate does not subtract the BigQuery or Cloud Run monthly free tiers, nor the account’s trial credits.

Official pricing references: [BigQuery pricing](https://cloud.google.com/bigquery/pricing), [Cloud Run pricing](https://cloud.google.com/run/pricing), and [Artifact Registry pricing](https://cloud.google.com/artifact-registry/pricing). BigQuery on-demand pricing lists $6.25/TiB for this region and a 1 TiB monthly free tier; Cloud Run lists $0.000018 per vCPU-second and $0.000002 per GiB-second before free tier. These rates make the measured compute forecast less than $0.10 including the prior Week-4 estimate of under $0.02, far below the $5 Week-5 aim and $10 operational target. Storage and settled billing remain separate uncertainties.

Billing API remains disabled, no billing upgrade was made, and no hard budget cap is configured. The authenticated Console showed an active trial and no DataForge current-month project row during the Week-5 preflight. Exact settled charges and remaining credits are therefore unknown; the $10 value is an operational target, not a cap.

## Cleanup

- Deleted the nine exact Week-5 `staging.week5_events_*` tables after saving their IDs, row counts, and expiration times to `temporary_staging_cleanup.json`. The post-cleanup inventory found none remaining.
- Deleted the two exact-generation benchmark scratch objects under `tmp/week5/benchmark/` and the five scratch tables after collecting job receipts. The bucket’s seven-day soft-delete policy keeps deleted object generations recoverable during that window; `performance_benchmark.json` records the generations and deletion receipt.
- Kept the declared `silver`, `gold`, `ops`, and single Cloud Run Job plus the current r7 image digest.
- Artifact Registry’s `dockerConfig.immutableTags=true` prevented deleting superseded r1–r6 tags (`FAILED_PRECONDITION`). The cleanup receipt is `artifact_registry_cleanup.json`. No tag-immutability policy change was attempted; r1–r6 and their image manifests remain, adding a small unmetered storage residual.
- Kept the quarantined INC-07 invalid manifest and the one valid but unused over-broad source batch as audit evidence; both are listed in `gcs_generations.json`.
- No schedule, always-on service, VM, Cloud SQL, GKE, Composer, Spark, or Week-6/7 resource was created.
