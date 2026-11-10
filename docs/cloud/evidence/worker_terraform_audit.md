> HISTORICAL: captured before authentication recovery and selection of a new isolated project. Current status/target: docs/cloud/week4_acceptance.md and docs/cloud/target.json.

# Worker report â€” Terraform and IAM audit

**Scope:** Read-only Terraform, IAM, state, and adapter review.
**Cloud commands / writes:** None.
**File changes by worker:** None.

## Initial findings and remediation

- Terraform required an explicit project ID and had no stale project default, but local default state was not project-isolated. A fresh, empty project-named workspace is now used; the default workspace was empty and remains unselected.
- Terraform's provider quota project needed explicit alignment. The provider now sets `user_project_override = true`, and Python client credentials request the approved project quota explicitly.
- That quota-project behavior requires `serviceusage.services.use`. Terraform now grants `roles/serviceusage.serviceUsageConsumer` to the runtime identity and optional local transfer principal; the deployer must already have permission. No grant is applied.
- A completed BigQuery retry previously stopped at `create_table(... exists_ok=False)`. The implementation now checks table provenance, schema, row count, and exact raw and typed values before reusing completed tables. Incomplete/conflicting tables fail closed and are not deleted automatically.
- GCS objects remain create-only and are re-read and SHA-256-verified on reuse; region checks precede writes.
- The design creates no APIs, static keys, Owner/Editor binding, Cloud Run job, scheduler, VM, Cloud SQL, GKE, Composer, or Spark cluster.

## Remaining risks

- The approved project IAM policy, service availability, API state, billing linkage, and live bucket/dataset locations remain unverified because the isolated SDK profile has no authenticated account and the current ADC read returned 403.
- The local Terraform plan is refresh-disabled and is not safe to apply. A fresh refreshed plan is required after the correct identity is authorized.
- `roles/storage.bucketViewer` is documented as Beta; confirm it is acceptable in the approved project before apply.
- No hard spending cap is configured; USD 5 is only the user's operational target.
