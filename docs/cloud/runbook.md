# P7.1 Week-4 cloud runbook

**Current state:** The isolated foundation is applied. All 11 synthetic source uploads passed, all 11 safe reruns reused matching outputs, and runtime positive/negative IAM checks passed. Measured usage and cost estimates are recorded in [cloud_cost_receipt.md](cloud_cost_receipt.md); billing settlement remains unverified and the independent final controller returned CLOUD_GO_WEEK4; read the authoritative [controller verdict](controller_verdict.md) for release readiness.

## 1. Read the approved target and enter the isolated session

From `D:\DATA_ENGINEER\DataForge`:

```powershell
. .\scripts\enter_dataforge_cloud.ps1
$target = Get-Content -Raw .\docs\cloud\target.json | ConvertFrom-Json
$project = $target.project_id
$projectNumber = $target.project_number
$bucket = $target.bucket
$region = $target.region
$config = $target.configuration
```

The helper reads [target.json](target.json), selects the isolated SDK directory under `%USERPROFILE%\.config\gcloud-dataforge-p7-lab`, and uses the target-named gcloud configuration and ADC file. It does not change persistent user environment settings. Verify the configured project and quota project without printing credentials:

```powershell
gcloud --configuration=$config config get-value core/project
gcloud --configuration=$config config get-value billing/quota_project
gcloud --configuration=$config config get-value compute/region
gcloud --configuration=$config projects describe $project --format="value(projectNumber,lifecycleState)"
```

The project, region, bucket, workspace, SDK directory, and project number are in `target.json`; do not copy stale values from prior shared-project notes. Cloud Resource Manager is enabled for this target, so the earlier empty `--billing-project=` workaround is unnecessary. Do not alter the quota project or print authentication data.

Historical authentication troubleshooting remains in the private local authentication diagnosis (excluded from publication). The old `%APPDATA%` SDK root is not the active configuration.

## 2. Local synthetic preflight

The local preflight is network-free. It verifies the selected source against the complete active manifest, schema, hashes, row count, synthetic classification, and unique keys:

```powershell
.\.venv\Scripts\python.exe -m dataforge.cli cloud-preflight --source geography
.\.venv\Scripts\python.exe -m dataforge.cli cloud-transfer `
  --source geography `
  --project $project `
  --bucket $bucket `
  --dataset staging `
  --region $region `
  --bucket-location $region `
  --dataset-location $region `
  --dry-run
```

A dry-run location match is not live verification. The deployed bucket and datasets were checked in [live_foundation_inventory.json](evidence/live_foundation_inventory.json).

## 3. Applied Terraform foundation

The refreshed plan in workspace `p7-dataforge-p7-lab-d0f725` had 11 creates, 0 updates, and 0 deletes; the exact reviewed plan was applied successfully. The saved binary plan remains private. See [the plan/apply receipt](terraform_plan.md), [sanitized plan summary](evidence/reviewed_plan_summary.json), and [post-apply drift receipt](evidence/terraform_drift.json).

For a future approved Terraform change, read `target.json` and select its workspace. Use the pinned binary/provider, generate a **new refreshed plan**, review every resource and IAM change, and apply only that exact plan after the change is explicitly approved. Do not reuse a prior plan or state from another project. `transfer_member` stays unset while the Project Owner performs uploads. Set `TF_VAR_runtime_test_member` privately to the verified operator only if the scoped keyless impersonation grant is still required; do not record the principal in source or logs.

```powershell
$tf = Join-Path $env:TEMP 'dataforge-terraform-1.17.1\terraform.exe'
$dir = 'cloud/terraform/dev'
& $tf "-chdir=$dir" workspace select $target.terraform_workspace
& $tf "-chdir=$dir" init -backend=false -lockfile=readonly -input=false
$env:TF_VAR_project_id = $project
$env:TF_VAR_bucket_name = $bucket
$env:TF_VAR_region = $region
Remove-Item Env:TF_VAR_transfer_member -ErrorAction SilentlyContinue
$plan = Join-Path $env:TEMP 'dataforge-p7-lab-week4-reviewed.tfplan'
& $tf "-chdir=$dir" plan -refresh=true -input=false -no-color "-out=$plan"
& $tf "-chdir=$dir" show -no-color $plan
```

After a separately approved plan review, apply only the saved artifact:

```powershell
& $tf "-chdir=$dir" apply -input=false $plan
```

## 4. Transfer and safe reruns

The first pass completed for all 11 synthetic sources: 16,259 rows and 235,910 Parquet bytes. Geography was the initial eight-row smoke and its raw/typed BigQuery checks passed. All 11 reruns then passed with unchanged row counts, source/Parquet hashes, GCS generations, table names, and raw/typed value checks; the matching load and cast outputs were reused. Receipts are in [transfers](evidence/transfers/) and [reruns](evidence/reruns/).

The following command illustrates one explicitly requested source run. Avoid repeating uploads when an existing receipt already proves a successful matching run:

```powershell
.\.venv\Scripts\python.exe -m dataforge.cli cloud-transfer `
  --source geography `
  --project $project `
  --expected-project-number $projectNumber `
  --bucket $bucket `
  --dataset staging `
  --region $region `
  --execute
```

The adapter uses generation-match zero, checks the object bytes and generation, loads exact Parquet bytes into raw staging, casts into a separate typed table, and verifies keys, schemas, values, and job receipts. Do not delete or overwrite conflicting objects/tables to force a retry.

## 5. Runtime IAM smoke

The keyless `dataforge-runtime` account successfully read the geography object and matched its SHA-256, then ran a BigQuery query with eight rows and eight unique keys. Anonymous private-object access returned HTTP 403; runtime access to Gold returned HTTP 403. No service-account key was created. Details are in [iam_live_verification.json](evidence/iam_live_verification.json).

The operator's `roles/iam.serviceAccountTokenCreator` binding applies to this service account only. The role lets that principal act with the service account's existing permissions. It remains for reproducible Week-5 identity checks; remove it with a separately reviewed plan if no longer required. The runtime itself has no Silver/Gold access.

## 6. Cost and stop rules

- The project is linked to the existing active Free Trial; no billing upgrade was made.
- The operational target is **USD 10**, not a hard spending cap. The [cost receipt](cloud_cost_receipt.md) records actual job bytes and a conservative task estimate below USD 0.02. Settled billing has not posted and is not inferred to be zero.
- Never publish the personal credit balance, billing-account identifiers, credential records, or browser screenshots.
- Stop future work if the project or quota project differs from `target.json`, the billing link is unavailable, required permissions are absent, locations differ, unexpected resources appear, or the cost estimate exceeds the target.

## 7. Safe cleanup

The bucket contains immutable source objects/manifests and all three datasets are managed in the new workspace. Staging tables expire after seven days; only `tmp/` objects have a 30-day lifecycle rule. The bucket, datasets, and runtime service account have Terraform deletion protection; the bucket is not force-destroyed. No cloud resources were deleted during Week 4.

Keep Terraform state and saved plans private. Any cleanup that changes or deletes resources requires a fresh reviewed plan and explicit approval for the exact deletion. Preserve source objects, manifests, GCS generations, BigQuery job receipts, and billing evidence until separately approved. See [cleanup.md](cleanup.md).

Cloud Run Jobs, scheduling, incremental checkpoints, Silver merges, and Gold publication remain future Week-5/7 scope.
