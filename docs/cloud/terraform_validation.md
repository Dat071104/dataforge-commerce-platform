# Terraform formatting, validation, deployment, and state-isolation receipt

**Date:** 2026-11-09 (Asia/Bangkok)
**Terraform:** 1.17.1
**Google provider:** 8.9.0, exact version constraint and lock entry
**Target:** `dataforge-p7-lab-d0f725` (`955038620072`)
**Workspace:** `p7-dataforge-p7-lab-d0f725`

## Checks and deployment

| Command / action | Result |
|---|---|
| `terraform -chdir=cloud/terraform/dev fmt -recursive` | Exit 0 |
| `terraform -chdir=cloud/terraform/dev fmt -check -recursive` | Exit 0 |
| `terraform -chdir=cloud/terraform/dev init -backend=false -lockfile=readonly -input=false` | Exit 0; pinned Google provider reused |
| `terraform -chdir=cloud/terraform/dev validate -no-color` | Exit 0; configuration valid |
| New project-named workspace | Created for the new project; no prior project's state was reused |
| Refreshed reviewed plan | Exit 0; 11 creates, 0 updates, 0 deletes; SHA-256 in [terraform_plan.md](terraform_plan.md) |
| Apply of reviewed plan | Exit 0; 11 added, 0 changed, 0 destroyed |
| Post-apply detailed drift check | Exit 0; `no_changes=true`, 11 managed resources |

The plan summary, live inventory, and drift receipt are [reviewed_plan_summary.json](evidence/reviewed_plan_summary.json), [live_foundation_inventory.json](evidence/live_foundation_inventory.json), and [terraform_drift.json](evidence/terraform_drift.json).

## State and identity separation

The stack uses Terraform's default local backend. The new workspace is isolated from the old shared-project workspace; root confirms it was created fresh and no old state was reused. Local state and saved plans remain private and ignored by Git. Do not move them into repository evidence.

The current target is declared once in [target.json](target.json). The session helper, [enter_dataforge_cloud.ps1](../../scripts/enter_dataforge_cloud.ps1), reads that target and selects the isolated gcloud root under `%USERPROFILE%\.config\gcloud-dataforge-p7-lab`. Authentication files stay outside the repository; do not print or commit them. The earlier `%APPDATA%` path and authentication failure are historical context in the private local authentication diagnosis (excluded from publication), not the current deployment configuration.

The required Service Usage, Cloud Resource Manager, Cloud Storage, BigQuery, IAM, and IAM Credentials APIs were enabled in the new project before apply. The live inventory also lists BigQuery dependency APIs. Terraform source does not enable APIs. The project is linked to the existing active Free Trial without a billing upgrade; this is not a cost cap.

This receipt covers source validation, isolated project deployment, and drift. It does not replace transfer receipts or the root-owned usage/cost receipt. The independent final controller issued [CLOUD_GO_WEEK4](controller_verdict.md); hosted CI remains required before merge.
