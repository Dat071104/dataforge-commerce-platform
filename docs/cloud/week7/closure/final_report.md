# P7.4.1 Week 7 syllabus closure — final evidence report

**Evidence date:** 2026-11-13 (Asia/Bangkok).
**Status:** independent controller returned `CLOUD_GO_WEEK7_SYLLABUS`; PR #6 merged after exact-head hosted CI passed. Two recovery requirements remain partial.
**Branch:** `feature/p7-week7-syllabus-closure`, based on accepted `main` SHA `765324c6e9cd798b5080fcd977465b1d3ac843b0`.
**Scope:** isolated Mini-project 3 weather pipeline. Accepted Week 4/5/6/7 releases and commerce data remain unchanged.

## Demonstrated

- **Mini-project 3 API → Bronze → BigQuery → dbt → Gold:** Open-Meteo ERA5, three allowlisted provinces, observation date 2026-11-05. The live API path wrote immutable raw/typed Bronze artifacts and a COMPLETE manifest with exact generations and SHA-256 provenance. The successful automatic Scheduler execution and successful Airflow DagRun both landed and reconciled three rows, ran dbt build/tests, and published the weather-only Gold pointer. See [end-to-end receipt](api_to_gold_e2e_receipt.json).
- **Timed cloud scheduling:** Cloud Scheduler fired automatically at 2026-11-12 08:55 UTC (15:55 Asia/Ho_Chi_Minh). Workflow `5028cbfb-e5a2-4596-b663-6d0d964a8c56` succeeded and published version 3. The one-shot job was paused and deleted after the demonstration; no schedule remains enabled. See [scheduler receipt](scheduler_execution_receipt.json).
- **Airflow integration:** Airflow 3.4.0 ran locally in Docker as a real integration DagRun against the GCP data plane. It invoked Cloud Run, waited for an immutable GCS receipt, loaded and reconciled BigQuery, ran dbt build/test/publish, and verified Gold publication version 4 with three rows. Airflow itself was not hosted in GCP. See [Airflow receipt](airflow_integration_receipt.md).
- **SCD2 history:** isolated synthetic input produced three observed versions (`CREATED`, `PROCESSING`, and a `CANCELLED` tombstone), adjacent validity windows, exactly one current version, no overlap, and no new version on unchanged replay. Week 5's authoritative history was not modified. See [SCD2 receipt](dbt_scd2_history_receipt.json).
- **Failure notification:** one approved controlled failure opened a Monitoring incident and the user confirmed that the single email arrived. No second test was sent. The temporary channel and policy were removed. See [redacted delivery receipt](notification_delivery_receipt.md).
- **Recovery:** exact manifest replay retained three landing grains without duplicates or changing the current Gold pointer. An unsettled-date request and an incorrect manifest generation failed closed. A controlled failure after dbt tests but before publication preserved the current version 4 Gold pointer. See [reconciliation and recovery](reconciliation_and_recovery.md).
- **Parity:** the isolated full-refresh weather target matched the incremental target for the demonstrated date: three rows on each side, zero `EXCEPT DISTINCT` differences.

## Open limitations

The acceptance matrix remains evidence based and does not claim every proposed fault injection was completed:

- Airflow retry configuration is covered by DAG contract tests, but a transient live GCP task failure followed by an observed Airflow retry was not injected.
- No live GCS object tampering, bad BigQuery schema, failing dbt quality candidate, or concurrent duplicate trigger was attempted. Local contracts cover related rejection behavior; they are not live cloud acceptance evidence.
- Airflow scheduler/UI were local Docker. Cloud Composer, GKE, and always-on VMs were not used.
- The schedule, alert channel, alert policy, and temporary IAM grants were removed after their one-time demonstrations. No recurring alert or schedule remains active.
- Cost figures are usage-based list-price estimates, not settled billing. Billing-account free-tier consumption and final charges remain unknown.

See the [acceptance matrix](acceptance_matrix.md) for each MET/PARTIAL/NOT MET item and exact evidence. The user reported mentor approval of GCP as the Azure/Fabric alternative; no separate written approval artifact was provided.

## Cost and cleanup summary

Observed usage supports an estimated gross Cloud Run plus BigQuery list-price subtotal of about **USD 0.095** for the bounded weather work, before free-tier credits and unpriced/uncertain storage, logging, Workflow, Monitoring, and network charges. OCI metadata for the 21 observed weather image digests totaled about 283 MiB of unique compressed layers; the billing-account free tier may cover this, but account-wide usage is unknown. These are estimates, not a bill. Details and official pricing links are in [IAM, cost, and cleanup](iam_cost_cleanup.md).

Temporary Scheduler/IAM resources and notification resources were removed. The final refreshed Terraform plan reported no infrastructure changes. Scheduler job count, Monitoring notification channel count, and alert policy count are all zero. Existing accepted commerce resources and datasets were not targeted by this closure.

## Verification and release state

The offline repository regression most recently completed with **194 passed and 7 skipped** (`RUN_POSTGRES_TESTS=0`). Skips are the explicitly gated operational/PostgreSQL integration cases. The focused Mini3/Airflow logic checks completed with **28 passed and 17 subtests**; Ruff, Python compilation, dbt offline parse and selectors, Terraform format/validation, JSON parsing, and secret/diff checks passed. Earlier authorized evidence records six PostgreSQL integration passes using unique temporary databases. The final refreshed Terraform plan reported no changes. Airflow DAG import/structure tests passed 4/4 in the pinned Airflow 3.4.0 image with `network=none`; the current host's Docker daemon is unavailable, so that image-specific check was not rerun during this final local pass.

The isolated gcloud configuration still names the School account and approved project, but its CLI credential currently asks for interactive refresh. The ADC-backed Resource Manager read returned HTTP 200 with the expected project number and ACTIVE state, and Terraform refreshed successfully through ADC. This is a credential-refresh issue, not a project IAM denial; no cloud write was attempted through the failing CLI session.

The one independent controller returned `CLOUD_GO_WEEK7_SYLLABUS`. PR [#6](https://github.com/Dat071104/dataforge-commerce-platform/pull/6) merged at `4939d1d887555528d6622400b4a8c9ab16bec86c`. Exact-head CI ran on `e1c0f00eec4ebbff0bbf5371e066b0bd18cb6443`: GitHub reported 12/12 checks successful or skipped (11 successful, one skipped dbt compile job because pull-request workflows receive no GCP identity). Local `main` was fast-forwarded to the merge commit and contains the feature commit. Historical `CLOUD_GO_WEEK7` remains intact and separate from P7.4.1.
