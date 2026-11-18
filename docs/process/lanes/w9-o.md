# W9 Worker O (DataOps) — O1–O3 / O-PR1

**Trạng thái:** O1–O3 implementation and local checks are complete. I-1 is applied: all 24 planned resources are now in Terraform state after one provider-only retry. After G-B, the provider condition was narrowed to the four approved Week-9 workflow files and expected events by an in-place 0/1/0 update. No API enable, image build/push, or deployment occurred. GitHub-side WIF positive/negative tests, exact-head CI, and toolbox smoke remain `UNVERIFIED`.

**Worktree:** `D:\DATA_ENGINEER\DataForge_w9_o` · branch `feat/w9-o-1` · base `ab345f7ae502d3e29d2c88b0dd5b8996319ffbf0`.

## Files thay đổi

- `.github/workflows/week9-dataops.yml` — một job `lint` cho O2 và một job Actions-only để build/smoke toolbox cho O3; không có cloud job.
- `.pre-commit-config.yaml` — Ruff, SQLFluff BigQuery/Jinja, yamllint, Gitleaks, Data Contract lint.
- `cloud/terraform/week9_dataops/{main,wif,datasets,secrets,variables,outputs,versions}.tf` — WIF, CI identities/IAM, datasets, empty secrets, outputs, pinned provider/backend.
- `cloud/terraform/week9_dataops/.terraform.lock.hcl` — Google provider 8.9.0 checksums, được tạo bởi Terraform 1.17.1 và giữ lại theo yêu cầu integrator.
- `deploy/dataops_toolbox/Dockerfile`, `requirements.in`, `requirements.lock` — Python 3.12 toolbox và hash-pinned dependencies.
- `docs/process/lanes/w9-o.md` — báo cáo lane này.

Không sửa ADR, board, plan, hay Terraform files thuộc Q/G.

## O1 — Terraform

- WIF pool/provider dùng claims dạng số `repository_id=1446796465` và `repository_owner_id=242334093`, cùng `workflow_ref` giới hạn tới `week9-dataops.yml`, `week9-cleanup.yml`, `week9-cd.yml`, `week9-catalog.yml`; event allowlist là `pull_request`, `push`, `workflow_dispatch`, `schedule`.
- Hai service accounts: `dataforge-w9-ci-dbt` và `dataforge-w9-meta-read`; không tạo key.
- Custom role chỉ có `bigquery.datasets.create`. CI dbt SA nhận `bigquery.jobUser`, `logging.logWriter`, dataset `dataViewer` chỉ trên `weather_mini3` và `dbt_weather_mini3`, dataset `dataEditor` chỉ trên `w9_drill` và `dataforge_dq`, cùng `secretAccessor` ở hai secret cụ thể. Metadata SA chỉ có BigQuery metadata viewer và Data Catalog viewer.
- Tạo `w9_drill`, `dataforge_dq`, `restricted_pii`, `pii_safe` tại `us-central1`, label `week=w9`. `w9_drill` và `restricted_pii` có table expiration 7 ngày. `dataforge_dq`, `restricted_pii`, `pii_safe`, WIF, identities, role, secrets và IAM bindings còn lại có deletion protection. `w9_drill` và IAM binding riêng của nó vẫn có thể bị xóa khi close-out.
- Secret Manager chỉ tạo hai secret container (`w9-slack-webhook-url`, `w9-pii-hmac-key`); không có `secret_version` resource hay secret value trong repo.
- Tất cả Terraform lệnh đều chạy sau khi dot-source `D:\DATA_ENGINEER\DataForge\scripts\enter_dataforge_cloud.ps1` và kiểm tra project là `dataforge-p7-lab-d0f725` trong cùng PowerShell command.

Sau fresh cost preflight của integrator, guarded read-only plan cuối cùng hoàn tất với `-lock=false`: **24 to add, 0 to change, 0 to destroy**. `terraform show -no-color` đầy đủ ở:

`C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-final-readonly-plan.txt`

Binary plan đi kèm ở `C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-final-readonly.tfplan`. Đây chỉ là artifact để integrator review; **DO NOT APPLY** trước integration gate.

Các địa chỉ trong plan:

```text
google_bigquery_dataset.dataforge_dq
google_bigquery_dataset.pii_safe
google_bigquery_dataset.restricted_pii
google_bigquery_dataset.w9_drill
google_bigquery_dataset_iam_member.ci_read_weather_datasets["dbt_weather_mini3"]
google_bigquery_dataset_iam_member.ci_read_weather_datasets["weather_mini3"]
google_bigquery_dataset_iam_member.ci_write_dataforge_dq
google_bigquery_dataset_iam_member.ci_write_w9_drill
google_iam_workload_identity_pool.github_dataforge
google_iam_workload_identity_pool_provider.github_oidc
google_project_iam_custom_role.w9_dataset_creator
google_project_iam_member.ci_dataset_creator
google_project_iam_member.ci_job_user
google_project_iam_member.ci_log_writer
google_project_iam_member.meta_catalog_viewer
google_project_iam_member.meta_metadata_viewer
google_secret_manager_secret.w9["w9-pii-hmac-key"]
google_secret_manager_secret.w9["w9-slack-webhook-url"]
google_secret_manager_secret_iam_member.ci_secret_accessor["w9-pii-hmac-key"]
google_secret_manager_secret_iam_member.ci_secret_accessor["w9-slack-webhook-url"]
google_service_account.ci_dbt
google_service_account.meta_read
google_service_account_iam_member.ci_dbt_workload_identity_user
google_service_account_iam_member.meta_read_workload_identity_user
```

**Plans:** the earlier pre-retention plan and the 24/0/0 final plan above are stale and **DO NOT APPLY**. The old binaries remain at `C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-readonly.tfplan` and `C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-final-readonly.tfplan`; automatic review rejected deletion of the older binary and no retry occurred. The provider-only plan `C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-provider-retry-20261118.tfplan` was **APPLIED** (`1 add / 0 change / 0 destroy`) and must not be reapplied. Its readable `terraform show` output is `C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-provider-retry-20261118-plan.txt`.

## I-1 partial apply RCA

The first application created the datasets, service accounts, project/dataset IAM bindings, custom role, pool, and empty secret containers. It failed only on `google_iam_workload_identity_pool_provider.github_oidc`. Cloud Audit Logs recorded `google.iam.v1.WorkloadIdentityPools.CreateWorkloadIdentityPoolProvider`, status 3 (`INVALID_ARGUMENT`): the provider display name exceeded the 32-character limit. The original value was `GitHub OIDC - DataForge commerce platform` (41 characters). The corrected value is `GitHub OIDC - DataForge W9` (26 characters). Terraform `fmt -check` and `validate` passed after this fix. Full evidence is in [`terraform-i1-wif-provider-rca-20261118.md`](../week9/evidence/terraform-i1-wif-provider-rca-20261118.md).

No BigQuery data or secret version was written and no API was enabled. A read-only provider inventory first confirmed the pool existed and provider did not. After the display-name fix, the reviewed provider-only plan applied successfully; a second provider inventory returned the full provider name, and Terraform state now contains 24/24 resources. The initial apply wrapper omitted the process exit/session metadata; the partial outcome was reconstructed from state and audit logs and recorded as one `TOOLING_SLIPS` increment. No unchanged-code apply was repeated.

## G-B trust-condition follow-up

Controller G-B returned REVISE because the initial provider condition accepted any workflow from the authorized repository. The integrator added `workflow_ref` and `event_name` mappings and restricted the provider to the four AF9 Week-9 workflow files and expected events while retaining numeric repository/owner checks. Fresh plan: **0 add / 1 in-place change / 0 destroy**; apply succeeded. A metadata-only provider description confirmed the condition. GitHub positive/negative WIF tests remain **UNVERIFIED** until network access returns; add a negative test for an unapproved workflow before enabling WIF in O4.

## O2 — Lint foundations

`week9-dataops.yml` có một `lint` job, `permissions: contents: read`, timeout và concurrency. Trên runner, checkout được stage để Gitleaks hook quét toàn bộ nội dung; Data Contract CLI cài đúng 1.2.8. Workflow còn có job build/smoke toolbox của O3, không push image.

Kết quả local:

- `pre-commit validate-config`: pass.
- Ruff 0.14.6: **142 Python files pass**. Bốn file legacy bị loại trừ sau 5 lỗi import-order có sẵn tại base: `labs/spark_nyc_taxi/managed/job.py`, `local_oracle.py`, `preflight.py`, `tests/test_local_oracle.py`.
- SQLFluff 3.4.2, BigQuery/Jinja: **10 SQL files pass**. Exclude đúng 24 file legacy dưới đây; baseline scan thấy 213 findings trong 23 file và SQLFluff bỏ qua file macro >20 KB. Các exclude chỉ chạm đúng path cũ, file Week 9 mới vẫn được lint.
- yamllint 1.37.1 strict, relaxed rules, line max 160: **15 YAML files pass**; exclude 8 file legacy có warnings.
- `datacontract lint`: **3/3 contract files pass**, mỗi file chạy một check. Hook gọi CLI một file mỗi lần vì CLI chỉ nhận một location.

SQLFluff baseline excludes:

```text
dbt/dataforge/macros/weather_mini3_publication.sql
dbt/dataforge/macros/week7_publication.sql
dbt/dataforge/models/intermediate/int_week5_payment_control_by_order.sql
dbt/dataforge/models/intermediate/int_week7_batch_control.sql
dbt/dataforge/models/marts/fct_week7_build_receipt.sql
dbt/dataforge/models/marts/fct_week7_order_reconciliation.sql
dbt/dataforge/models/weather/intermediate/int_weather_daily.sql
dbt/dataforge/models/weather/marts/fct_mini3_weather_daily.sql
dbt/dataforge/models/weather/marts/mart_weather_province_daily.sql
dbt/dataforge/models/weather/staging/stg_weather_mini3_landing.sql
dbt/dataforge/snapshots/week5_orders_history.sql
dbt/dataforge/snapshots/week7_scd2_proof_history.sql
dbt/dataforge/tests/assert_mart_weather_province_daily_calendar_windows.sql
dbt/dataforge/tests/assert_mart_weather_province_daily_metric_ranges.sql
dbt/dataforge/tests/assert_mini3_weather_gold_matches_silver.sql
dbt/dataforge/tests/assert_mini3_weather_grains_unique.sql
dbt/dataforge/tests/assert_mini3_weather_landing_complete_requests.sql
dbt/dataforge/tests/assert_mini3_weather_metric_ranges.sql
dbt/dataforge/tests/assert_week7_active_payments_have_order.sql
dbt/dataforge/tests/assert_week7_all_silver_orders_are_present.sql
dbt/dataforge/tests/assert_week7_candidate_matches_week5_gold.sql
dbt/dataforge/tests/assert_week7_order_reconciliation_math.sql
dbt/dataforge/tests/assert_week7_published_batches_have_check.sql
dbt/dataforge/tests/assert_week7_scd2_proof_windows.sql
```

yamllint baseline excludes:

```text
.github/workflows/ci.yml
.github/workflows/dbt-docs-pages.yml
.github/workflows/week7-ci.yml
.github/workflows/week8-ci.yml
cloud/workflows/week7_weather_workflow.yaml
cloud/workflows/week7_workflow.yaml
contracts/mart_weather_province_daily.v1.yaml
contracts/weather_landing.v1.yaml
```

Ruff baseline excludes:

```text
labs/spark_nyc_taxi/managed/job.py
labs/spark_nyc_taxi/managed/local_oracle.py
labs/spark_nyc_taxi/managed/preflight.py
labs/spark_nyc_taxi/managed/tests/test_local_oracle.py
```

Gitleaks hook is configured but was not run locally: GitHub REST failed on current Wi-Fi and the hook repo was not fetched. A `detect-secrets --all-files -n` scan returned 478 untriaged candidates across 147 files; this is not a clean secret-scan result. Run Gitleaks on the branch before any push.

## O3 — DataOps toolbox

`requirements.in` pins `dbt-bigquery==1.11.3`, `datacontract-cli==1.2.8`, and `great-expectations==1.25.0` (GX Core). `requirements.lock` has hashes for all 134 resolved packages. `uv pip install --dry-run --require-hashes` passed in a clean CPython 3.12.13 environment. The earlier `--system` attempt conflicted with a pre-installed unrelated `google-cloud-storage==3.1.1`; the isolated run passed.

The Dockerfile installs with `--require-hashes` and runs as UID 10001. GitHub Actions builds with gzip compression and runs `dbt --version`, `datacontract --version`, plus exact package-version/GX import assertions. No local Docker was used; image build/smoke remains CI-only and `UNVERIFIED`.

## Check ↔ fixture mapping

O1–O3 add no fault detector or fault fixture, so there is no new `check_id` ↔ fixture pair in this lane. Fault-matrix work is deferred to O4/O6 and Q’s fixtures.

## CI and open risks

- GitHub exact-head workflow run IDs: **UNVERIFIED**; no PR run was started in this lane. GitHub REST lookup failed on current Wi-Fi; integrator requested one switch to 5G for the batched GitHub work.
- `actions/checkout` v7.0.1 and `actions/setup-python` v7.0.0 SHAs came from local verified refs. Docker Buildx/build-push action SHAs remain pending remote verification.
- Gitleaks must run before push; no clean secret-scan claim is made from the untriaged detect-secrets candidates.
- Lint exclusions cover only exact pre-existing paths. Remove them when those files are repaired; do not extend them to Week 9 files.
- I-1 provider creation is complete. GitHub-side WIF positive/negative tests remain `UNVERIFIED` until the exact-head workflow can run. The next cloud plan is Worker G's AF4 plan; refresh cost preflight and review it separately before apply.

## Integrator actions

1. Run Gitleaks before push; verify Docker action SHAs when GitHub access is available.
2. Push/open O-PR1, record exact-head CI run IDs, and require both lint and toolbox smoke jobs green before merge order advances.
3. Run the WIF positive/negative tests from I-1 after the exact-head workflow can obtain the approved GitHub OIDC identity.
4. Review Worker G's AF4 plan separately after refreshing cost preflight; do not combine it with the already-applied O1 root.
5. Extend this workflow in O-PR2 with cloud/contract/dbt/diff/fault-matrix jobs; add explicit notices to any fork/cloud jobs that skip.
