# Safe cleanup and Terraform state handling

## Current deployed state

The active target is the new project `dataforge-p7-lab-d0f725`, declared in [target.json](target.json). The Week-4 foundation was applied in the fresh workspace `p7-dataforge-p7-lab-d0f725`; the verified plan created 11 resources and the post-apply drift check found no changes. The project contains a private GCS Bronze bucket, BigQuery `staging`/`silver`/`gold` datasets, the keyless runtime service account, scoped IAM, and synthetic source objects/tables. See [live_foundation_inventory.json](evidence/live_foundation_inventory.json), [Terraform plan/apply receipt](terraform_plan.md), and [terraform_drift.json](evidence/terraform_drift.json).

No cloud deletion or destroy operation was run. Existing SaigonBite resources in the earlier shared-project target were not imported, managed, or changed.

## Terraform and data protections

- The stack uses the default local backend. Keep state and saved plan artifacts private; do not commit them or copy them into repository evidence. The new project-named workspace is not interchangeable with another project's state.
- `.gitignore` excludes `.terraform/`, Terraform state, plan files, `*.tfvars`, and crash logs. Do not force-add any of them.
- The GCS bucket, all three BigQuery datasets, and runtime service account use Terraform deletion policy `PREVENT`. The bucket has `force_destroy = false`; datasets use `delete_contents_on_destroy = false`.
- The bucket lifecycle rule deletes only objects under `tmp/` after 30 days. Bronze source objects and manifests are retained. Staging tables expire after seven days; Silver and Gold have no default table expiration.
- No locked retention policy is configured. The adapter prevents overwrite with generation preconditions and verifies bytes/generation; that is not WORM protection. Check effective soft-delete and retention behavior before any object cleanup.
- The optional operator Token Creator binding is scoped to the runtime service account. It supports keyless verification; remove it only through a separately reviewed plan if it is no longer needed.

## If cleanup is later approved

1. Pause any future schedule/job and record the target project inventory and usage/cost status.
2. Back up local Terraform state privately and verify the backup. Preserve source manifests, object generations, BigQuery job receipts, and any data that must remain.
3. Generate a fresh reviewed plan for the exact requested deletion. List every object, table, dataset, IAM binding, bucket, and service account it would affect. `PREVENT` should block bucket/dataset/service-account deletion unless the protection is deliberately changed in a reviewed plan.
4. Remove only the specifically approved ephemeral resources. Do not use `force_destroy`, blanket bucket removal, or project-wide deletion.
5. Verify the resulting resource inventory, state, and usage after cleanup. Retain the state backup and receipts until the project owner confirms the final state.

No automatic `terraform destroy` command or CI cleanup is configured. The operational cost target is USD 10, not a spending cap; use the root-owned cost receipt before deciding what to retain or clean up.
