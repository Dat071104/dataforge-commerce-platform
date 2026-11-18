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

- Ở O1/G-B applied state, WIF pool/provider dùng numeric repository/owner IDs và allowlist bốn Week-9 workflows; event list lúc đó có `pull_request`. O-PR2 đổi HCL sang `pull_request_target`, nhưng change này chưa được plan/apply. Dùng applied state làm chuẩn tới khi integrator review/apply.
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

# O-PR2 — O4–O8 DataOps delivery (code only; CI/cloud evidence pending)

**Branch/base:** `feat/w9-o-2` from `origin/main` `3a20050e813700cd0a050c69aa1dbd652ca9fc08`; preserve root commit `986d8fb` and the I-2 cost-ledger update. No push, merge, apply, or API enable was done.
**Files changed for O-PR2:** `.github/workflows/week9-dataops.yml`, `.github/workflows/week9-wif-deny.yml`, `.github/workflows/week9-cleanup.yml`, `.github/workflows/week9-cd.yml`, `.github/CODEOWNERS`, `.github/pull_request_template.md`, `cloud/terraform/week9_dataops/wif.tf` (event list only), `dbt/dataforge/profiles.example.yml`, `deploy/dataops_toolbox/requirements.in`, `deploy/dataops_toolbox/requirements.lock`, `deploy/dataops_toolbox/wif_permission_probe.py`, `deploy/dataops_toolbox/week9_live_faults.py`, `deploy/dataops_toolbox/tests/test_week9_workflow_contract.py`, and this lane report.

## O4 — CI and WIF boundary

- Static `lint` and `toolbox` checks stay on `pull_request` with read-only permissions. WIF-capable jobs use `pull_request_target` and an immutable first-step repo-ID check (`head.repo.id == repository_id`) before checkout/auth; fork PR cloud jobs emit an explicit skip notice. Same-repo PR head checkout happens only after the gate.
- The provider HCL event list now requests `pull_request_target` in place of `pull_request` while retaining `push`, `workflow_dispatch`, and `schedule`. This is code-only; no Terraform plan/apply or WIF exchange was run. The integrator must review/apply the provider update before WIF tests.
- Manual `week9-dataops.yml` inputs include `run_wif_smoke`, `run_cloud_build`, `run_fault_matrix`, and `pr_number`. The manual cloud-build path accepts only a positive numeric PR number whose open same-repository PR head SHA exactly matches the dispatched ref; it derives the dataset as `dbt_ci_pr_<number>` and accepts no dataset name.
- With `run_cloud_build=true`, `pr-comment` now runs after the cloud job, revalidates the exact open same-repository PR head, and downloads that run's sanitized summary artifact using the validated PR number. It therefore produces the same PR summary/bytes comment for manual exact-head proof as for trusted target PR runs.
- Manual `run_fault_matrix` targets the fixed `w9_drill` dataset; no PR-number or arbitrary dataset value controls its live target. The manual `run_wif_smoke` path checks positive `bq ls w9_drill` and expected `bq ls silver` authorization denial.
- The W7 write-denial helper calls BigQuery `tables.testIamPermissions` only as advisory evidence because that API can fail open. It then submits a `jobs.query` request with `dryRun=true` against `weather_mini3.weather_landing`; only a 403 specifically naming `bigquery.tables.updateData` counts as denial. Accepted dry-run or another response remains UNVERIFIED/fails the check. No real production write is sent.
- `.github/workflows/week9-wif-deny.yml` is a separate manual workflow outside the applied workflow allowlist. It exchanges its OIDC token directly with STS and passes only if the response identifies an attribute-condition rejection. It never prints the token or STS body.
- Trusted PR cloud build creates only `dbt_ci_pr_<number>` with 24-hour table TTL and labels; reads a 7-date weather slice from `weather_mini3`, writes the slice/model outputs only to the PR dataset, applies the 1-GiB per-job cap, runs dbt build/unit tests and G1, and computes a same-date read-only diff. The PR comment uses a sanitized JSON summary and reports measured copy/dbt-adapter/diff bytes where available; G1 Python query billing stays explicitly UNVERIFIED.
- Toolbox gates run `pytest tests/week9` plus the O-owned static workflow safety tests, dbt parse and PII guard offline, contract lint, and `datacontract breaking` against `origin/main`. The toolbox lock now includes `pytest==8.4.2`.
- Removed a duplicate set of unit, offline dbt/PII, and contract compatibility steps so each offline gate runs once per toolbox job.

## O5 — cleanup

`week9-cleanup.yml` keeps automatic closed-PR cleanup on `pull_request_target` with the same repository-ID gate. Manual cleanup requires `run_cleanup=true` plus a positive numeric `pr_number`; GitHub metadata must confirm a merged PR from this repository, then the workflow derives only `dbt_ci_pr_<number>`. Supplying a number without the explicit boolean runs a notice only. The scheduled/manual sweep considers **closed PRs inactive for at least 48 hours**, then checks the dataset’s actual BigQuery `creationTime` is also at least 48 hours before deletion. It does not enumerate unrestricted project datasets or touch W7 resources.

## O6 — fault matrix

- The local matrix covers F01–F12, F-T1, and F-N0 one fixture per run with Q’s captured-fixture harness. F07/F10 are marked deferred in those local rows.
- F07/F10 live tests run only in CI, only in `w9_drill`, under the `pull_request_target` same-repo gate or explicit manual `run_fault_matrix=true` dispatch. F07 makes isolated `landed_at` stale by 73 hours and expects the source-freshness artifact to be `error`; F10 injects `rain_day=true` with zero precipitation into an isolated mart table and expects the exact P1 dbt test to fail. The live helper restores the captured clean source/mart and compares the restored `w9_drill` Gold slice hash before/after each fault. It never reads or writes W7 data.
- `fault_matrix_report.md` combines local and live rows; absent live artifacts remain UNVERIFIED. No fault or alert result is claimed until CI executes it.

**Mapping ID ↔ fixture:** F07 → `G2.SOURCE.FRESHNESS` / stale `landed_at` in `w9_drill`; F10 → `G2.WEATHER.RAIN_PRECIP_CONSISTENCY` / synthetic mart mismatch in `w9_drill`. F01–F06, F08–F09, F11–F12, F-T1, F-N0 use the IDs/fixtures in `tests/week9/faults/manifest.yml` and Q’s harness. F13–F15 remain separate PR fixtures.

## O7/O8 — artifacts, Pages handoff, ownership

- `week9-cd.yml` is named exactly **Week 9 main artifacts** and on main runs offline `dbt parse`. It uploads `dataforge-prod-manifest/manifest.json` and `week9-dq-report/dq-report.md` (artifact-root file copied from `tests/week9/fault_matrix_report.md`). The existing Pages workflow remains untouched. Integrator’s Pages integration commit `c296eb0` is pending cherry-pick/review.
- `.github/CODEOWNERS` assigns `contracts/`, `governance/`, and `cloud/terraform/week9_dataops/` to `@Dat071104`. The PR template has a Data impact section. No GitHub ruleset was changed; integrator adds required checks after one green main run.

## Focused local checks and limits

Local command summary:

```text
uvx --from yamllint==1.37.1 yamllint --strict ...
uvx --from pre-commit==4.3.0 pre-commit validate-config .pre-commit-config.yaml
uvx --from ruff==0.14.6 ruff check deploy/dataops_toolbox/wif_permission_probe.py deploy/dataops_toolbox/week9_live_faults.py deploy/dataops_toolbox/tests/test_week9_workflow_contract.py
python -m py_compile deploy/dataops_toolbox/wif_permission_probe.py deploy/dataops_toolbox/week9_live_faults.py deploy/dataops_toolbox/tests/test_week9_workflow_contract.py
python -m pytest -q -p no:cacheprovider deploy/dataops_toolbox/tests/test_week9_workflow_contract.py
uv pip install --dry-run --require-hashes --python <clean Python 3.12 env> -r deploy/dataops_toolbox/requirements.lock
YAML parse and bash -n on each extracted run block in the four Week 9 workflows; AST parse embedded Python heredocs
```

- Strict yamllint: passed for the W9 workflows, profile example, and CODEOWNERS; `pre-commit validate-config` passed.
- Final YAML parse passed for **4** Week 9 workflows; Bash syntax passed for **58** extracted run blocks. The **5** O-owned workflow contract tests passed; they cover exact manual PR binding/comment artifact, explicit cleanup selection, closed/old-only sweep, and fixed `w9_drill` F07/F10 scope.
- Ruff and `py_compile` passed for `wif_permission_probe.py`, `week9_live_faults.py`, and the new static workflow test.
- Hashed dependency dry-run in clean Python 3.12: **137 packages, pass**.
- The focused host test passed (**5 passed**). A broader host run of `tests/week9` plus the static tests was **29 passed / 17 failed** because host Python lacks `great_expectations`; the toolbox lock pins GX Core 1.25.0, so those G1 tests remain for the pinned toolbox CI environment. No source/dependency changes were made in response.
- No dbt warehouse run, WIF exchange, GCP command, Terraform formatting/validation/plan/apply, local Docker, or OpenMetadata was run. Exact-head CI IDs and WIF/F07/F10 live results remain **UNVERIFIED**. Terraform formatting/validation were simply not run; no plan/apply or cloud-side provider update was attempted because cloud authentication is expired and the integrator prohibited cloud actions.
- Because `pull_request_target` uses the base-branch workflow, pre-merge proof is manual from the selected OPR2 ref: `run_wif_smoke=true`; `run_cloud_build=true` with the exact positive `pr_number` for `dbt_ci_pr_<n>`; or `run_fault_matrix=true` for fixed `w9_drill`. `week9-wif-deny.yml` is dispatched separately. No dispatch was run by Worker O.

## Integrator actions

1. Review/apply the provider event-list change before any WIF test. Then dispatch the safe WIF smoke and the separate `week9-wif-deny.yml`; inspect the expected STS attribute-condition denial and the non-mutating W7 write probe caveat.
2. Run Gitleaks before push, open O-PR2, and record exact-head run IDs. Keep all WIF/fault live evidence UNVERIFIED until CI completes.
3. Dispatch `run_cloud_build=true` with the exact open PR number/head for pre-merge proof; for F07/F10 dispatch `run_fault_matrix=true` to the fixed `w9_drill` path only.
4. After merge, dispatch cleanup with `run_cleanup=true` and the exact numeric merged PR number, then verify only `dbt_ci_pr_<number>` is deleted. Keep the stale sweep limited to closed/inactive PR datasets.
5. Cherry-pick Pages integration `c296eb0`; require the `Week 9 main artifacts` workflow and artifact name/path exactly as above. Add ruleset checks only after one green main run.
