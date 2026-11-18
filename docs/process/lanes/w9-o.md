# W9 Worker O (DataOps) — O1–O3 / O-PR1

**Trạng thái:** phần triển khai O1–O3 đã xong ở mức `implemented`; local checks bên dưới đã chạy. Exact-head CI và toolbox image smoke test còn `UNVERIFIED`. Không có Terraform apply, API enable/disable, image push hay deployment.

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

- WIF pool/provider dùng claims dạng số `repository_id=1446796465` và `repository_owner_id=242334093` trong provider condition; không dùng tên repo làm điều kiện duy nhất.
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

**Plan superseded:** trước khi thêm `prevent_destroy` và tách IAM của `w9_drill`, một plan cũ 24/0/0 đã được lưu. Text file cũ được gắn `STALE — DO NOT APPLY`. Binary cũ còn tại `C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-readonly.tfplan`; việc xóa binary bị automatic policy review từ chối, không thử lại. **DO NOT APPLY** binary cũ. Chỉ plan cuối cùng phía trên mới khớp HCL hiện tại.

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
- Final Terraform plan is read-only and for review only. Integrator must approve it through the normal integration gate before apply; no API enable or apply was performed.

## Integrator actions

1. Review the final plan artifact and the retained-resource `prevent_destroy` choices. Re-run a fresh plan if the HCL changes.
2. Run Gitleaks before push; verify Docker action SHAs when GitHub access is available.
3. Push/open O-PR1, record exact-head CI run IDs, and require both lint and toolbox smoke jobs green before merge order advances.
4. Apply Terraform only after normal review/approval and required cost preflight; then run the WIF positive/negative tests from I-1.
5. Extend this workflow in O-PR2 with cloud/contract/dbt/diff/fault-matrix jobs; add explicit notices to any fork/cloud jobs that skip.
