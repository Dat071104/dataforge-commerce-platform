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

Gitleaks hook is configured. The CI run above passed Gitleaks; the post-fix commit still needs the requested pre-push Gitleaks scan. A `detect-secrets --all-files -n` scan returned 478 untriaged candidates across 147 files; this is not a clean secret-scan result.

## O3 — DataOps toolbox

`requirements.in` pins `dbt-bigquery==1.11.3`, `datacontract-cli==1.2.8`, and `great-expectations==1.25.0` (GX Core). `requirements.lock` has hashes for all 134 resolved packages. `uv pip install --dry-run --require-hashes` passed in a clean CPython 3.12.13 environment. The earlier `--system` attempt conflicted with a pre-installed unrelated `google-cloud-storage==3.1.1`; the isolated run passed.

The Dockerfile installs with `--require-hashes` and runs as UID 10001. GitHub Actions builds with gzip compression and runs `dbt --version`, `datacontract --version`, plus exact package-version/GX import assertions. No local Docker was used; image build/smoke remains CI-only and `UNVERIFIED`.

## Check ↔ fixture mapping

O1–O3 add no fault detector or fault fixture, so there is no new `check_id` ↔ fixture pair in this lane. Fault-matrix work is deferred to O4/O6 and Q’s fixtures.

## CI and open risks

- CI run `44358354537` on exact head `dd0a0e62`: `DataOps lint` (including Gitleaks) passed; only toolbox smoke failed. The local quoting fix below has not yet been rerun in CI, so its follow-up run ID remains **UNVERIFIED**.
- `actions/checkout` v7.0.1 and `actions/setup-python` v7.0.0 SHAs came from local verified refs. Docker Buildx/build-push action SHAs remain pending remote verification.
- Gitleaks must run before push; no clean secret-scan claim is made from the untriaged detect-secrets candidates.
- Lint exclusions cover only exact pre-existing paths. Remove them when those files are repaired; do not extend them to Week 9 files.
- I-1 provider creation is complete. GitHub-side WIF positive/negative tests remain `UNVERIFIED` until the exact-head workflow can run. The next cloud plan is Worker G's AF4 plan; refresh cost preflight and review it separately before apply.

## Integrator actions

1. Run Gitleaks on the post-fix commit before the next push; verify Docker action SHAs when GitHub access is available.
2. Push/open O-PR1, record exact-head CI run IDs, and require both lint and toolbox smoke jobs green before merge order advances.
3. Run the WIF positive/negative tests from I-1 after the exact-head workflow can obtain the approved GitHub OIDC identity.
4. Review Worker G's AF4 plan separately after refreshing cost preflight; do not combine it with the already-applied O1 root.
5. Extend this workflow in O-PR2 with cloud/contract/dbt/diff/fault-matrix jobs; add explicit notices to any fork/cloud jobs that skip.

## O-PR1 CI RCA — run 44358354537 (`dd0a0e62`)

- `DataOps lint` (including Gitleaks) passed; only `DataOps toolbox build and smoke` failed.
- Root cause: the Python version assertions were passed through a shell single-quoted `python -c '...'` argument, while the f-string expressions also contained single-quoted package names. The shell ended the argument early and Python raised `NameError: name 'dbt' is not defined`.
- Resolution: pass the unchanged assertions through a single-quoted Bash heredoc (`python - <<'PY' ... PY`) on `docker run --interactive`. The three exact checks remain `dbt-bigquery==1.11.3`, `datacontract-cli==1.2.8`, and GX Core `1.25.0`.
- Focused validation of the fix: strict yamllint, `bash -n` on the extracted step, and Python AST parse all passed. No local Docker run; post-fix CI result remains `UNVERIFIED`.

# O-PR2 — O4–O8 DataOps delivery (code-only)

**Branch/base:** `feat/w9-o-2` from `origin/main` `3a20050e813700cd0a050c69aa1dbd652ca9fc08`; the integrator's existing root commit `986d8fb` and `docs/week9/cost_ledger.md` were left untouched.

## O4 — CI and keyless permission gates

- Static lint/toolbox work remains on `pull_request` with no `id-token: write`. WIF-enabled jobs use `pull_request_target` and an immutable first-step repository-ID gate (`head.repo.id == repository_id`) before PR-head checkout or authentication. Fork cloud jobs emit a visible skip notice. The WIF provider event allowlist in `cloud/terraform/week9_dataops/wif.tf` now names `pull_request_target` instead of `pull_request`; this HCL change is **not planned or applied** and needs integrator review before WIF tests.
- The allowed `week9-dataops.yml` workflow has a dispatch input `run_wif_smoke`. Its keyless job checks project context, runs positive `bq ls w9_drill`, and confirms `bq ls silver` returns an authorization denial.
- `deploy/dataops_toolbox/wif_permission_probe.py` calls `tables.testIamPermissions` on `weather_mini3.weather_landing` as advisory evidence, then submits only a BigQuery `jobs.query` request with `dryRun=true` for an UPDATE-shaped statement. It accepts only an HTTP 403 naming `bigquery.tables.updateData`; accepted dry-runs and other errors remain `UNVERIFIED`. No actual CREATE/INSERT/UPDATE/DELETE is issued. The output explicitly records the fail-open limitation of `testIamPermissions`.
- `.github/workflows/week9-wif-deny.yml` is a separate manual workflow deliberately excluded from the applied provider allowlist. It exchanges an OIDC token directly with STS and passes only when the rejection identifies the provider attribute condition. The OIDC token and STS response body are never printed.
- Trusted PR builds create only `dbt_ci_pr_<number>` with 24-hour table expiration and Week/PR labels; the source slice is read from `weather_mini3` and written only to that PR dataset. dbt uses the `w9_ci` profile with a 1-GiB maximum per job, runs the slim manifest selection when available (full weather fallback otherwise), dbt unit tests, the G1 gate, and a same-date read-only data comparison. A sanitized PR comment records changed models, test counts, measured copy/diff bytes, and comparison counts; dbt adapter-reported billed bytes are included when available. The G1 Python client does not expose its job's billed bytes, so the comment labels that measurement `UNVERIFIED` and states the cap.
- The toolbox job also runs W9 pytest, offline dbt parse, the PII guard, contract lint, and `datacontract breaking` against `origin/main`. The lock now includes `pytest==8.4.2`.

## O5 — cleanup

`week9-cleanup.yml` deletes only the closed PR's validated `dbt_ci_pr_<number>` dataset. A weekly/manual sweep uses GitHub PR metadata as candidate IDs, then checks each dataset's actual BigQuery `creationTime` and deletes only datasets at least 48 hours old. Fork cleanup is skipped visibly. Dataset-list project permissions are not added.

## O6 — fault matrix

`week9-dataops.yml` has a matrix over F01–F12, F-T1, and F-N0. Local captured-fixture faults run individually with Q's harness; F07 and F10 are explicitly deferred from the local harness and run only in the `pull_request_target` isolated BigQuery job. `week9_live_faults.py` injects stale `landed_at` and the F10 rain/precipitation mismatch only into `dbt_ci_pr_<number>`, checks the expected dbt states/check ID, restores the source/model, and compares a read-only production Gold hash before/after. It uploads `fault_matrix_report.md`; no alert is sent by these jobs.

## O7 — main artifacts and Pages handoff

`week9-cd.yml` is named exactly **Week 9 main artifacts**. On main it runs offline `dbt parse`, then uploads `dataforge-prod-manifest/manifest.json` and `week9-dq-report/dq-report.md` (copied from `tests/week9/fault_matrix_report.md`). The existing Pages workflow remains integrator-owned and untouched. The integrator has prepared Pages integration commit `c296eb0` on their branch for cherry-pick after this lane is ready.

## O8 — ownership and review preparation

- `.github/CODEOWNERS` assigns `contracts/`, `governance/`, and `cloud/terraform/week9_dataops/` to `@Dat071104`.
- `.github/pull_request_template.md` now has a Data impact section for sources, targets, grain, contract compatibility, PII, production versus isolated reads/writes, byte cap, cost, and cleanup.
- No GitHub ruleset was changed. Integrator action: add the verified required check names only after a green run on main.

## Local evidence and limits

- Strict yamllint: passed for the four Week 9 workflows and `profiles.example.yml`.
- `pre-commit validate-config`: passed.
- Bash syntax check: **54** workflow run blocks passed; Python AST parse: **5** embedded scripts passed.
- Ruff and `py_compile`: both passed for `wif_permission_probe.py` and `week9_live_faults.py`.
- Hashed dependency dry-run in a clean Python 3.12 environment: passed with **137** resolved packages.
- No `pytest`, Docker, dbt warehouse run, GCP command, Terraform command, or WIF exchange was run locally. Exact-head CI run IDs and live F07/F10 evidence remain **UNVERIFIED**.
- O1 retained-resource policy is unchanged. The WIF event-list change needs a reviewed plan/apply by the integrator; no Terraform plan was run because GCP auth is expired and the integrator prohibited cloud actions.

## Integrator actions

1. Review and apply the WIF provider event change, then run the manual `run_wif_smoke=true` workflow and the `week9-wif-deny.yml` negative test. Do not treat the advisory `testIamPermissions` response alone as proof; require the dry-run's expected authorization response.
2. Run Gitleaks, push/open O-PR2, and record each exact-head CI run. The new workflow file paths must be present in the applied WIF allowlist before their cloud jobs can authenticate.
3. Cherry-pick the Pages integration commit `c296eb0` after reviewing the `week9-dq-report/dq-report.md` artifact contract.
4. Add main-ruleset required checks only after one successful run on main. No ruleset or deployment change was made by Worker O.

# O-PR2 — O4–O8 (code chuẩn bị; chưa có CI/cloud evidence)

**Branch/base:** `feat/w9-o-2` trên `origin/main` `3a20050e813700cd0a050c69aa1dbd652ca9fc08`. Root commit `986d8fb` và `docs/week9/cost_ledger.md` được giữ nguyên.

## O4 — WIF boundary, PR CI và quality gates

- `.github/workflows/week9-dataops.yml` giữ lint, Gitleaks, toolbox, Python unit/contract/PII checks ở `pull_request` với `contents: read`.
- WIF job chuyển sang `pull_request_target`. Bước đầu tiên so sánh `github.event.pull_request.head.repo.id` với `github.repository_id`; chỉ sau đó checkout PR head cùng repo và gọi Google auth. Fork PR không được checkout hoặc cấp OIDC; có skip notice riêng.
- Repository variables được tham chiếu đúng bằng tên, không ghi/echo giá trị: `W9_WIF_PROVIDER`, `W9_CI_DBT_SA_EMAIL`, `W9_META_READ_SA_EMAIL`.
- Trusted/manual WIF smoke kiểm tra `bq ls w9_drill`, kỳ vọng `bq ls silver` trả authorization deny, và chạy `wif_permission_probe.py` cho `weather_mini3.weather_landing`. Probe `tables.testIamPermissions` được ghi rõ là advisory vì API có thể fail-open. Bước thứ hai gửi duy nhất `jobs.query` `dryRun=true` cho UPDATE-shaped statement; chỉ HTTP 403 nêu `bigquery.tables.updateData` mới tính là deny. Accepted dry-run hay lỗi khác là `UNVERIFIED`/fail; không có INSERT/UPDATE/DELETE thật.
- `.github/workflows/week9-wif-deny.yml` là manual negative workflow không nằm trong provider allowlist. Nó trao đổi OIDC token với STS, chỉ pass nếu lỗi đúng `invalid_grant` do attribute condition. Token và error body không được in.
- Cloud PR job tạo/reset riêng `dbt_ci_pr_<number>` (24h table TTL, labels), copy 7 ngày gần nhất từ `weather_mini3` vào dataset PR, rồi chạy dbt build/unit/G1 và cùng-date diff. Mọi BigQuery query có cap 1 GiB. Source reads production là read-only; writes chỉ vào dataset PR/`dataforge_dq`.
- Toolbox gates gồm pytest, dbt parse offline, PII manifest guard, contract lint và `datacontract breaking` với `origin/main`. PR comment được post bởi job riêng, chỉ với summary JSON đã lọc; không cấp `pull-requests: write` cho job chạy dbt.
- `w9_ci` profile trong `profiles.example.yml` đặt `maximum_bytes_billed=1073741824` và `job_execution_timeout_seconds=600`.

## O5 — cleanup

`week9-cleanup.yml` dùng `pull_request_target` cho closed PR, same-repository ID gate trước WIF, rồi xóa dataset có tên khớp `dbt_ci_pr_<n>`. Weekly/manual sweep lấy số PR từ GitHub metadata, kiểm tra `creationTime` BigQuery, rồi xóa dataset age ≥48h. Không cần project-wide dataset-list grant. Fork cleanup được skip rõ ràng.

## O6 — fault matrix

- `fault-matrix-local` chạy matrix F01–F12, F-T1, F-N0 từng fixture một bằng Q harness; F07/F10 local cases được ghi UNVERIFIED/deferred.
- `fault-matrix-live` chạy riêng ở trusted `pull_request_target`, checks PR dataset בלבד: F07 đặt `landed_at` 73h cũ rồi yêu cầu dbt `sources.json` status `error`; F10 thay mart PR thành `rain_day=true, precipitation_mm=0`, yêu cầu G2 singular test fail với đúng `check_id`, rồi khôi phục mart/source. F10/F07 compare production Gold hash trước/sau bằng read-only query.
- `fault-matrix-report` hợp nhất artifact rows, ưu tiên F07/F10 live CI rows, và giữ UNVERIFIED rows nếu live artifact không có.

**Mapping ID ↔ fixture:** F07 → `G2.SOURCE.FRESHNESS` / isolated PR `weather_landing` stale 73h; F10 → `G2.WEATHER.RAIN_PRECIP_CONSISTENCY` / isolated PR mart mismatch. F01–F06, F08–F09, F11–F12, F-T1, F-N0 → IDs/fixtures in `tests/week9/faults/manifest.yml` and Q’s captured fixture harness. F13–F15 remain separate PR fixtures per plan.

## O7/O8 — main artifact handoff and ownership

- `week9-cd.yml` workflow name is exactly `Week 9 main artifacts`; it uploads `dataforge-prod-manifest/manifest.json` and `week9-dq-report/dq-report.md` (copy of `tests/week9/fault_matrix_report.md`). Pages workflow remains untouched because it is integrator-owned. Integrator’s `c296eb0` Pages integration is pending cherry-pick/review.
- `.github/CODEOWNERS` assigns `contracts/`, `governance/`, and `cloud/terraform/week9_dataops/` to `@Dat071104`. The PR template now has a Data impact section. No GitHub ruleset was changed; integrator adds required checks only after one green main run.

## Focused local checks

- Strict yamllint: passed for all four W9 workflows, `profiles.example.yml`, and `CODEOWNERS`.
- `pre-commit validate-config`: passed.
- Bash syntax: **54** workflow `run` blocks passed; Python AST: **5** embedded scripts passed.
- Ruff and `py_compile`: passed for both new toolbox helper scripts.
- Hashed requirements dry-run in clean Python 3.12 environment: **137 packages, pass**.
- No `pytest`, dbt warehouse run, WIF exchange, GCP command, Terraform command/plan/apply, Docker, or OpenMetadata was run locally.
- O-PR2 exact-head CI run IDs and all WIF/F07/F10 live evidence: **UNVERIFIED**. The `wif.tf` event allowlist edit is code only (`pull_request` removed; `pull_request_target` added); it must be reviewed/applied before any WIF test. No provider update or cloud write was performed by Worker O.

## Integrator actions

1. Review and apply the WIF provider event update, then run manual WIF smoke and `week9-wif-deny.yml`; the latter must fail STS for the expected attribute-condition reason.
2. Push/open O-PR2 only after Gitleaks; record exact-head CI IDs. Review `UNVERIFIED` outcomes explicitly, especially the non-mutating W7 write-denial probe and F07/F10 isolated tests.
3. Cherry-pick Pages integration `c296eb0` and confirm it consumes `week9-dq-report/dq-report.md` after `Week 9 main artifacts` succeeds.
4. Add ruleset required checks only after one green run on main. Do not apply further cloud changes from this lane.

## Dispatch and ruleset prep

`pull_request_target` executes the base-branch workflow. Until O-PR2 is present on main, the pre-merge I-5 WIF check must therefore be started manually from this branch with `run_wif_smoke=true`; `week9-wif-deny.yml` is separately dispatched to test the non-allowlisted workflow path. No run was started by Worker O. Candidate main-ruleset checks after one green main run are `DataOps lint`, `DataOps toolbox build and smoke`, `WIF positive and least-privilege probes`, `Isolated BigQuery PR build and G1 gate`, and the `Assemble fault_matrix_report.md` report job. The integrator owns adding them.
