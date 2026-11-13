# Lane D — Learning closures

## Result — 2026-11-13

**Branch/base:** `feat/w1-w6-learning-closures` from `main` at `7cd204caa29e17c35137272d9ee3b406caef17eb`.

**Code commit:** `d07550553c5195c91b37084e5258d07a530a678d` (`feat(learning): add week 1-6 verification labs`).

### D1 — Polars/Pandas parity

- Added the fixed eight-row orders fixture and three-province dimension fixture. Both pipelines read CSV, filter delivered rows, join on `province_id`, group by province, and write/read Parquet.
- `tests/learning/test_parity_pipeline.py` asserts the Pandas result, Polars result, and their Parquet round-trips equal the same expected rows.
- Seven timed repeats after one warm-up reported local medians/standard deviations: Pandas **25.146 ± 1.076 ms**, Polars **8.489 ± 0.619 ms**. This is an eight-row local smoke measurement only, not a speedup claim.
- Timing environment was system Python 3.13.9, Pandas 3.0.6, Polars 1.36.1. The integrator pinned Polars 1.36.1 and `polars-runtime-32` in the dev dependency/lock for reproducible CI. The 1.x cap keeps the lab on the tested API; Polars 2.x changes lazy execution defaults and needs separate compatibility review. No package was installed by Lane D.

### D2 — q10 EXPLAIN plans

- Added a PostgreSQL integration test that creates/drops a unique synthetic database, runs the existing q10 query against a 150,000-row fixture, captures `EXPLAIN (ANALYZE, BUFFERS)`, applies the repository's candidate covering-index SQL, and captures the second plan. It writes plan text to `GITHUB_STEP_SUMMARY` on Actions and makes no speedup assertion.
- Local command with the existing loopback Postgres service: PowerShell loaded `DATABASE_URL` from `D:\DATA_ENGINEER\DataForge\.env` into the process without printing it, set `RUN_POSTGRES_TESTS=1`, then ran `python -m pytest -q -s tests/learning/test_q10_explain_plan.py` — **1 passed**. The test created and removed its unique `dataforge_explain_*` database; it did not touch application tables.
- Before the candidate index, PostgreSQL used the baseline `fct_item_order_date_idx` with a Bitmap Heap Scan (1,581 actual rows, 60 shared hits, 3 reads; 2.663 ms execution). After adding the candidate covering index, the planner still chose the baseline index (1,581 rows, 63 shared hits; 2.299 ms execution). These are separate observed plan times, not a causal comparison; the candidate index was present but not selected.
- The exact-head CI run that will execute this test in the disposable PostgreSQL 16 service is pending integration; no CI run was created by this lane.

### D3 — timestamp cursor counterexample

- Added a deterministic same-timestamp late-arrival fixture. After a consumer stores the first event's `updated_at`, a second event with the same timestamp is excluded by `updated_at > cursor`, while `change_seq > last_sequence` returns it.
- The test also checks the accepted Week 5 publisher orders/deduplicates by `change_seq` and applies strictly newer effective sequence values.

### D4 — Linux CLI mini-lab

- Added a local script/test that uses a pipe, `grep`, `awk`, `sed`, `chmod`, and `stat`; it reads only a test-local CSV and has no remote host or network call. The README contains one illustrative crontab entry for `scripts/week1_fetch_csv.sh` and exactly five SSH explanation lines.
- The executable shell test is intentionally skipped on Windows. It must run on the Linux CI runner; that run is pending integration.

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
- No GitHub Actions runs were created and no files were pushed. Exact-head CI is required to validate D4 on Linux, D2 on the CI Postgres service, and D1 after the integrator adds the pinned Polars dependency.

## Open risks

- The integrator added `polars>=1.36.1,<2` to the dev extra and pinned `polars==1.36.1` plus `polars-runtime-32==1.36.1` in the Python 3.11 lock. The parity suite passed in the supported Python 3.11 venv after this update; exact-head CI remains pending after rebase/push. Lane D did not install packages or edit dependency files.
- D2 was exercised against the local loopback Postgres service; its CI Postgres summary remains pending.
- D4's shell execution is Linux-only and was not run on Windows; exact CI must pass before this item is complete.
- No timing result justifies a library migration; use real workload measurements before changing the production dependency.

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
