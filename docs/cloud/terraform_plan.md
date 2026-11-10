# P7.1 Terraform plan and apply receipt — isolated target

**Date:** 2026-11-09 (Asia/Bangkok)
**Stack:** `cloud/terraform/dev`
**Terraform workspace:** `p7-dataforge-p7-lab-d0f725`
**Project:** `dataforge-p7-lab-d0f725` (`955038620072`)
**Region / bucket:** `us-central1` / `dataforge-p7-lab-d0f725-bronze`
**Reviewed plan SHA-256:** `4ED9CD3876E0F282253BD4C9A6E9199DCB7343C27A3790CF3BE121F786F88B40`

## Fresh plan and apply

A new workspace and isolated project target were used; no state from the earlier shared-project target was reused. The refreshed plan contained **11 creates, 0 updates, and 0 deletes**. Root reviewed and applied that exact plan: Terraform exited 0 with **11 added, 0 changed, 0 destroyed**. A subsequent detailed drift check exited 0 and reported no changes across all 11 managed resources.

The saved binary plan is private and is not committed. The sanitized resource list and plan hash are recorded in [reviewed_plan_summary.json](evidence/reviewed_plan_summary.json); the live inventory and drift receipts are [live_foundation_inventory.json](evidence/live_foundation_inventory.json) and [terraform_drift.json](evidence/terraform_drift.json).

## Planned resource groups

| Resource group | Create count | Scope |
|---|---:|---|
| Private Bronze bucket | 1 | New project, `us-central1`; uniform access and public access prevention |
| BigQuery datasets | 3 | `staging`, `silver`, `gold`; all `us-central1` |
| Runtime service account | 1 | Keyless `dataforge-runtime` |
| Bucket IAM | 2 | Runtime object reader and bucket metadata reader |
| Project IAM | 2 | Runtime BigQuery job user and Service Usage consumer |
| Staging dataset IAM | 1 | Runtime BigQuery data editor |
| Runtime impersonation IAM | 1 | Token Creator on the runtime service account only |

The optional `transfer_member` remained unset. The verified project Owner performed the one-time deployment and uploads; this identity is privileged and is not described as least privilege. The optional `runtime_test_member` was set privately to the verified operator so the runtime identity could be tested without a service-account key. No project-wide Token Creator grant was included.

## Current scope and gates

The new project is linked to the existing active Free Trial; no billing upgrade was made. The earlier shared-project target was superseded before deployment, and no SaigonBite or AskBetter resource was managed or changed. Required APIs were enabled in the new project before the plan; Terraform itself does not enable APIs.

This receipt verifies foundation deployment and drift only. The Week-4 source smoke and IAM checks have separate receipts. The operational cost target is USD 10, not a hard cap; measured usage is recorded in [the cost receipt](cloud_cost_receipt.md), while billing settlement remains unverified and the independent final controller returned CLOUD_GO_WEEK4. The authoritative [controller verdict](controller_verdict.md) is CLOUD_GO_WEEK4.
