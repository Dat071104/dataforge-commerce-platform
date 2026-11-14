# Lane D — Learning closures

## Result — 2026-11-13

**Branch/base:** feat/w1-w6-learning-closures rebased onto main merge SHA 8cca2c6337fc0db5abcfad8618d122fe17828a70. Rebased lane commits: code f687183df11be42d45e5f9efcb40d536282da88c; report fd246f963d7c1a37d44ebd1d296c6b156af56569; Polars dependency pin b1ef00d410bd531d9461c7ea48aa71797b83bbaf.

**Code commit:** f687183df11be42d45e5f9efcb40d536282da88c (`feat(learning): add week 1-6 verification labs`). Root dependency pin commit: b1ef00d410bd531d9461c7ea48aa71797b83bbaf.

### D1 — Polars/Pandas parity

- Added the fixed eight-row orders fixture and three-province dimension fixture. Both pipelines read CSV, filter delivered rows, join on `province_id`, group by province, and write/read Parquet.
- `tests/learning/test_parity_pipeline.py` asserts the Pandas result, Polars result, and their Parquet round-trips equal the same expected rows.
- Seven timed repeats after one warm-up reported local medians/standard deviations: Pandas **25.146 ± 1.076 ms**, Polars **8.489 ± 0.619 ms**. This is an eight-row local smoke measurement only, not a speedup claim.
- Timing environment was system Python 3.13.9, Pandas 3.0.6, Polars 1.36.1. The integrator pinned Polars 1.36.1 and `polars-runtime-32` in the dev dependency/lock for reproducible CI. The 1.x cap keeps the lab on the tested API; Polars 2.x changes lazy execution defaults and needs separate compatibility review. No package was installed by Lane D.

### D2 — q10 EXPLAIN plans

- Added a PostgreSQL integration test that creates/drops a unique synthetic database, runs the existing q10 query against a 150,000-row fixture, captures `EXPLAIN (ANALYZE, BUFFERS)`, applies the repository's candidate covering-index SQL, and captures the second plan. It writes plan text to `GITHUB_STEP_SUMMARY` on Actions and makes no speedup assertion.
- Local command with the existing loopback Postgres service: PowerShell loaded `DATABASE_URL` from `D:\DATA_ENGINEER\DataForge\.env` into the process without printing it, set `RUN_POSTGRES_TESTS=1`, then ran `python -m pytest -q -s tests/learning/test_q10_explain_plan.py` — **1 passed**. The test created and removed its unique `dataforge_explain_*` database; it did not touch application tables.
- Before the candidate index, PostgreSQL used the baseline `fct_item_order_date_idx` with a Bitmap Heap Scan (1,581 actual rows, 60 shared hits, 3 reads; 2.663 ms execution). After adding the candidate covering index, the planner still chose the baseline index (1,581 rows, 63 shared hits; 2.299 ms execution). These are separate observed plan times, not a causal comparison; the candidate index was present but not selected.
- At initial lane submission, the exact-head CI run for the disposable PostgreSQL 16 service was pending; see the root verification section below for the post-rebase local D2 run and remaining CI requirement.

### D3 — timestamp cursor counterexample

- Added a deterministic same-timestamp late-arrival fixture. After a consumer stores the first event's `updated_at`, a second event with the same timestamp is excluded by `updated_at > cursor`, while `change_seq > last_sequence` returns it.
- The test also checks the accepted Week 5 publisher orders/deduplicates by `change_seq` and applies strictly newer effective sequence values.

### D4 — Linux CLI mini-lab

- Added a local script/test that uses a pipe, `grep`, `awk`, `sed`, `chmod`, and `stat`; it reads only a test-local CSV and has no remote host or network call. The README contains one illustrative crontab entry for `scripts/week1_fetch_csv.sh` and exactly five SSH explanation lines.
- The executable shell test is intentionally skipped on Windows. It still must run on the Linux CI runner; root verification below records the Windows skip and pending exact-head CI.

### D5 — Power BI TMDL audit

- The targeted read-only TMDL text audit found **15 relationships**. None explicitly declares `fromCardinality`, `toCardinality`, or `crossFilteringBehavior`; this report does not infer default values.
- **Seven** relationships target `dim_date.date_key`. Shipment has an active `ship_date_key` relationship and one inactive `delivery_date_key` relationship; three shipment measures use `USERELATIONSHIP` for delivery-date reporting.
- No bridge table or bridge relationship is present. One RLS role, `South_Region_Viewer`, filters `dim_geography.region = "South"` and `dim_customer.customer_region = "South"`.
- No PBIP/TMDL source file was modified.

## Validation

- `python -m compileall -q labs/learning tests/learning` — **PASS**, exit 0.
- `python -m pytest -q tests/learning` — **6 passed, 2 skipped**. The skips are the Linux-only CLI test on Windows and opt-in PostgreSQL test without `RUN_POSTGRES_TESTS=1`.
- Project venv Python 3.11.9: `D:\DATA_ENGINEER\DataForge\.venv\Scripts\python.exe -m pytest -q tests/learning/test_change_cursor_counterexample.py tests/learning/test_powerbi_tmdl_audit.py tests/learning/test_linux_cli_lab.py` — **5 passed, 1 skipped** (Linux shell test skipped on Windows).
- Local D2 opt-in PostgreSQL test — **1 passed**, with before/after plan text captured above.
- `D:\DATA_ENGINEER\DataForge\.venv\Scripts\ruff.exe check labs/learning tests/learning` — **PASS** after the recorded I001 correction.
- `git diff --check` — **PASS**.
- `python scripts/week7_secret_scan.py` — **PASS**, zero findings across 509 files.
- The original lane worker created no GitHub Actions runs and pushed no files. After root rebase and local verification, exact-head Linux CI is required for D2 and D4 on the pushed branch.

## Open risks

- Polars remains capped below 2.x; compatibility with Polars 2 requires separate API review and parity tests.
- The q10 planner used the existing baseline index before and after the candidate index; no speedup is claimed.
- The Linux D4 regression test runs in Linux CI; it is skipped on Windows. Exact-head D4 passed in push run 43580786575.
- D PR Week7 attempt 1 had a timing-sensitive fifth-date backfill failure after four successful dates. One unchanged attempt 2 passed all six scenarios. Exact failed TaskInstance cause is unknown; no assertions or source code were changed for this incident.
- No GCP action or resource was created by Lane D. Current inventory and settled spend remain unavailable from the D-pack checklist H5 blocker.
## Root verification after rebase (2026-11-14)

- Rebased onto main merge SHA 8cca2c6337fc0db5abcfad8618d122fe17828a70. At verification time the local branch head was b1ef00d410bd531d9461c7ea48aa71797b83bbaf; this report update will add a documentation commit.

- Python 3.11 compileall passed; tests/learning passed 6 with 2 expected environment skips (Linux-only D4 and opt-in D2). Ruff passed; secret scan passed with 0 findings across 518 files; git diff --check origin/main...HEAD passed. Evidence log: D:\DATA_ENGINEER\DataForge_D_Week7_Final\evidence\lane-d-rebase-correct-root-2026-11-14.log; SHA-256 2DECFB10BF9BFA1A2CE3A4DF40B581E2CB11986AB65B9502CC37F45B32612E64.

- Opt-in PostgreSQL 16 D2 EXPLAIN test passed 1 after rebase. It created and dropped its unique synthetic database; an independent read-only check found 0 residual dataforge_explain_* databases. Before/after plan evidence: D:\DATA_ENGINEER\DataForge_D_Week7_Final\evidence\lane-d-postgres-explain-rebase-2026-11-14.log; SHA-256 4FBD26831E20C1D9F9DD63ACA5FEAD144E97F8FDE745D72311D462154395F894. The planner used the baseline index in both plans; no speedup claim is made.

- D2 exact-head CI Postgres summary remains required. D4 root cause: the grep filter selected delivered data rows and redirected them into delivered.csv without copying the CSV header. The minimal fix writes the header first, appends transformed rows, and reports data rows excluding the header. In cached apache/airflow:3.4.0-python3.11 with network_mode=none, bash -n and exact output assertions passed: header present, total 135.50, 2 data rows, pending/canceled excluded, mode 600. Evidence: D:\DATA_ENGINEER\DataForge_D_Week7_Final\evidence\lane-d-d4-linux-container-2026-11-14.log, SHA-256 A386AF57727C7E02E2C8068F5FE2751B137F93BB460CC51983FD7B61458ADD09. After the fix, Python 3.11 tests/learning passed 6/2, Ruff/compileall passed, secret scan found 0/518, and diff-check passed; log SHA-256 6D2A231690B598534B9080F30131DBBE49EEB0F08B3689BF4EE2352D8F369179. D2 opt-in Postgres result is recorded above; exact-head D2/D4 CI is pending.

## Root integration update after B merge (2026-11-14)

- Merged origin/main at 9ec5f75, which includes B PR #9 and the Airflow fix, into the D branch with normal merge commit b2e475cc9fa41b37fa390487f5b00b46576ba68a. The merge had no conflicts or history rewrite.
- Post-merge offline suite: tests/learning completed 6 passed and 2 expected skips (Windows-only D4 and opt-in D2). Evidence: D:\DATA_ENGINEER\DataForge_D_Week7_Final\evidence\lane-d-post-main-offline-2026-11-14.log; SHA-256 58E1CAC784D40E276B83BDBA989F72DD38E37A50710527F5D18BBE994EDEC6D5.
- Post-merge D2 opt-in PostgreSQL 16 EXPLAIN test: 1 passed, both plans recorded, and a follow-up query found 0 residual dataforge_explain_* databases. The planner used the baseline index in both plans, so no speedup is claimed. Evidence: D:\DATA_ENGINEER\DataForge_D_Week7_Final\evidence\lane-d-post-main-postgres-2026-11-14.log; SHA-256 EB2CFC0992D4D28A0F06E3BA4AB258B1D86BEBF32CB62D6C498496635BDB2895.
- Ruff, compileall, git diff --check, and secret scan passed; the scan found 0/553 files. The D4 Linux-only assertions were not changed; exact-head CI on the newly synced branch remains necessary for Linux D4 and the Postgres step.
- No cloud action, resource, paid query, or GCP cost was created for this update.
## Exact-head integration update after D PR checks (2026-11-14)

- D code head 4d64d41 is based on main 9bca18c through normal merge commit b2e475c. Post-sync local tests/learning passed 6 with 2 expected skips; opt-in PostgreSQL EXPLAIN passed 1 and residual test database count was 0; Ruff, compileall, diff check, and secret scan 0/553 passed.
- Exact-head base push 43580786421, Week 6 Spark push 43580786450, and Week 7 push 43580786575 passed. The Linux D4 test passed in the Week 7 Python regression job; the keyless compile was policy-skipped on the feature branch.
- Exact-head base PR run 43581796235 passed. Week 7 PR run 43581796293 attempt 1 failed the fifth synthetic backfill date after four successful dates and raised the harness timeout. One unchanged attempt 2 passed all six scenarios; Airflow job 132413625505 succeeded. No source or assertion change occurred between attempts.
- The failure is classified as a timing-sensitive FLAKY_INFRA candidate; the exact failed task state was not captured, so no root cause or speedup claim is made. The authorized unchanged retry budget is used for this incident.
- This report update changes the branch head; rerun exact-head CI before marking the D PR ready or merging. No cloud operation occurred.

## RCA log

### Ruff I001 in the timing helper

- **Symptom:** the targeted `ruff check labs/learning tests/learning` exited 1 with `I001` at `labs/learning/benchmark_parity.py:3`; the parity tests themselves passed.
- **Expected vs actual:** all lane Python files should satisfy repository import ordering; one import block was reported unsorted.
- **Reproduction:** `ruff check --diff labs/learning/benchmark_parity.py` showed the only proposed change was removing blank lines around the same-directory `parity_pipeline` import.
- **Hypothesis/evidence:** the helper import was separated from the pandas/Polars imports; Ruff's exact diff confirmed grouping/spacing, not name order or dependency.
- **Root cause:** an unnecessary blank line split the local helper import from the import group Ruff expects for this script.
- **Fix:** remove only the two blank separators; no code behavior changes.
- **Regression guard:** rerun the exact Ruff command and all `tests/learning` checks; verify `git diff --check`.

### Ruff formatting patch context mismatch

- **Symptom:** the narrow `apply_patch` hunk did not match `benchmark_parity.py`; no file changed.
- **Expected vs actual:** the hunk expected one blank line after the local helper import; the readback contained two blank lines.
- **Reproduction:** the rejected patch for the Ruff I001 whitespace fix.
- **Root cause:** the hunk copied an inaccurate blank-line count from the proposed Ruff diff.
- **Fix:** reapply against the exact three-line local import block and remove only the superfluous separators.
- **Regression guard:** rerun Ruff, the parity tests, and `git diff --check`.

### Incomplete Ruff I001 formatting fix

- **Symptom:** the full targeted Ruff command still reported the same `I001` after removing one blank line; no behavior tests failed.
- **Expected vs actual:** imports should match the formatter output; the diff showed one remaining blank line before `parity_pipeline`.
- **Reproduction:** `ruff check --diff labs/learning/benchmark_parity.py` after the first formatting correction.
- **Root cause:** the first minimal edit removed the extra blank line after the helper import but left the blank separator before it.
- **Fix:** remove the remaining blank line before the helper import to match Ruff's exact suggested diff.
- **Regression guard:** rerun targeted Ruff and the entire `tests/learning` suite.
