# P7.1 Week-4 deployment scope review

**Status:** Isolated foundation applied and live checks passed. All 11 first-pass source transfers and 11 safe reruns passed. The usage-based [cost receipt](cloud_cost_receipt.md) is complete; billing settlement remains unverified and the independent controller returned CLOUD_GO_WEEK4; the authoritative decision is [CLOUD_GO_WEEK4](controller_verdict.md).

## Project and boundary

The active DataForge target is the new project `dataforge-p7-lab-d0f725` (`955038620072`), declared in [target.json](target.json). It is separate from the earlier shared-project target. The new project is linked to the existing active Free Trial; no billing upgrade was made. Existing SaigonBite resources in the earlier shared project and the retired AskBetter project were not touched.

Root created a fresh Terraform workspace, reviewed a refreshed plan with **11 creates, 0 updates, 0 deletes**, and applied that exact plan successfully (**11 added, 0 changed, 0 destroyed**). The reviewed plan SHA-256 is `4ED9CD3876E0F282253BD4C9A6E9199DCB7343C27A3790CF3BE121F786F88B40`. Post-apply drift check reported no changes across 11 managed resources. See [plan](terraform_plan.md), [sanitized plan summary](evidence/reviewed_plan_summary.json), and [drift receipt](evidence/terraform_drift.json).

## Live foundation and IAM

- Private Standard GCS bucket `dataforge-p7-lab-d0f725-bronze` in `us-central1`, with uniform bucket-level access, public access prevention enforced, no public IAM members, and deletion protection.
- BigQuery `staging`, `silver`, and `gold` datasets in `us-central1`. Staging tables expire after seven days; Silver and Gold have no default expiration.
- Keyless `dataforge-runtime` service account. Its GCS roles are bucket-scoped; its BigQuery dataset write permission is limited to `staging`. Silver and Gold have no runtime access.
- One verified operator has Token Creator on the runtime service account only to support keyless identity tests. `transfer_member` remains unset; the project Owner performed the upload. That human deployer is privileged and is not claimed to be least privilege.
- Live IAM checks passed: runtime object read returned HTTP 200 and matched SHA-256; an eight-row BigQuery query returned eight unique keys; anonymous access to the private object returned HTTP 403; the runtime could not list Gold tables (HTTP 403); no static service-account key was created. The tested GCS permission was `storage.objects.get`.

The details are in [live_foundation_inventory.json](evidence/live_foundation_inventory.json) and [iam_live_verification.json](evidence/iam_live_verification.json).

## Data smoke and repeatability

The first pass transferred all 11 synthetic sources: **16,259 rows** and **235,910 Parquet bytes** in total. Geography was the initial eight-row smoke; its raw and typed tables passed schema, key, and exact-value reconciliation.

All 11 replay receipts now pass. For each source, the replay preserves row count, source and Parquet hashes, GCS generation, and raw/typed table names; raw and typed value checks match, and the existing load/cast outputs are reused. See [first-pass receipts](evidence/transfers/) and [rerun receipts](evidence/reruns/).

## Cost and remaining acceptance work

The operational target is **USD 10**, not a hard cap. The project is linked to the existing Free Trial without upgrading billing. No personal credit balance or billing-account identifiers are included here. Root is preparing the usage-based cost receipt from actual job bytes and current pricing; do not infer settled project spend before that receipt.

No VM, Cloud SQL, GKE, Composer, Cloud Run Job, Scheduler, recurring compute, or Spark service was deployed. A final independent controller review is still required after the cost receipt is recorded. Week-5/7 compute remains future scope, and this review does not assign final P7.1 acceptance.
