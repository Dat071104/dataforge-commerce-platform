# RCA — I-1 Workload Identity provider display-name rejection

**Status:** RESOLVED in Terraform. The provider-only retry was applied at 2026-11-18 22:53 +07; the full 24-resource state is present. GitHub-side WIF positive/negative tests remain **UNVERIFIED** until network access returns.

## Summary

The first I-1 apply used the reviewed O1 plan (`24 add / 0 change / 0 destroy`). Terraform created 23 resources, but `google_iam_workload_identity_pool_provider.github_oidc` was rejected by Google IAM. After the display-name fix, a reviewed provider-only plan was applied successfully; Terraform state and a read-only GCP provider listing now confirm all 24 resources, including the provider.

## Observed error

Cloud Audit Log at `2026-11-18T15:37:50.773766746Z` (`22:37:50 +07`) recorded:

```text
method: google.iam.v1.WorkloadIdentityPools.CreateWorkloadIdentityPoolProvider
status: 3 (INVALID_ARGUMENT)
message: The WorkloadIdentityPoolProvider's display name must be less than or equal to 32 characters.
```

The configured display name was `GitHub OIDC - DataForge commerce platform` (41 characters), exceeding the provider API limit. The repository and owner ID claims were otherwise valid, and `sts.googleapis.com` / `iamcredentials.googleapis.com` were already enabled.

## Impact and scope

- The initial partial apply left 23 of 24 resources in state; the corrected provider-only apply completed the 24/24 state.
- The WIF pool and provider now exist, but GitHub-side authentication has not been proven until a repository workflow can exchange its OIDC token.
- No secret versions, BigQuery data rows, query jobs, API enablements, or production-table writes occurred.
- All O1 resources are in project `dataforge-p7-lab-d0f725`; no Week 7 dataset received a write.
- The saved O1 plan binary is stale after the partial apply and is marked **DO NOT APPLY**.

## Fix and verification

- Shortened the provider display name in `cloud/terraform/week9_dataops/wif.tf` to `GitHub OIDC - DataForge W9` (26 characters).
- Guarded `terraform fmt -check` and `terraform validate` passed on the corrected HCL.
- Refreshed the cost preflight (W7 ≈USD 12.89274; W8 reserve ≤USD 0.10; W9 cap USD 3 / stop USD 2.4). The provider-only plan was `1 add / 0 change / 0 destroy`, saved to `C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-provider-retry-20261118.tfplan`, reviewed, and applied through `enter_dataforge_cloud.ps1`.
- Terraform state now contains all 24 planned resources. A read-only GCP provider inventory returned `projects/955038620072/locations/global/workloadIdentityPools/github-dataforge/providers/github-oidc`. The positive WIF workflow test and IAM negative tests remain unverified until GitHub access is restored.
- The failed 24/0/0 plan binaries remain stale and marked **DO NOT APPLY**. The provider-only retry plan was applied; do not reapply it.

## Tooling note

The initial exec wrapper did not preserve the Terraform command's exit status/session metadata. The partial apply outcome was reconstructed from Terraform state and the Admin Activity log. This is recorded as one `TOOLING_SLIPS` increment; no unchanged-code apply was repeated before the cause was identified.
