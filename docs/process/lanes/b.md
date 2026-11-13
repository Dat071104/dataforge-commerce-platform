# Lane B — dbt & Gold

## Result — 2026-11-13

**Branch/base:** `feat/w7-dbt-gold-mart` from `main` `7cd204caa29e17c35137272d9ee3b406caef17eb`.

### B1 — `mart_weather_province_daily`

- Added a `province_id, observation_date` Gold view over the existing `fct_mini3_weather_daily`, restricted to the single approved `open_meteo_era5` / `era5` input so the requested grain cannot multiply across provider models.
- Seven-day precipitation uses a numeric date `RANGE` over the current date and six prior calendar dates. It is `NULL` unless all seven dates have non-NULL precipitation; missing days are not treated as dry. Thirty-day temperature mean and anomaly use the current date plus 29 prior calendar dates and are `NULL` unless all 30 daily temperatures are present. The anomaly is current-day max temperature minus the inclusive trailing mean.
- Added an enforced dbt model contract, `not_null` / accepted province checks, and singular tests for grain uniqueness, ranges, rain-day consistency, complete-window semantics, and parity to an independent date-range calculation.
- Added a dbt unit test with a 61-row fixture: HCM has a missing calendar day, HN has a complete 30-day window, and DN carries unknown metrics. The test is discovered by dbt parse/selection, but its BigQuery execution was not run in this offline lane.

### B2 — source freshness and exposure

- Configured `weather_mini3.weather_landing` freshness using `landed_at`, warning at 36 hours and erroring at 72 hours. The 60-day Asia/Ho_Chi_Minh partition filter bounds the source freshness scan.
- Added the low-maturity `weather_province_daily_demo` dashboard exposure depending on the mart. It has no URL because no live dashboard exists; its description says so.

### B3 — static docs preparation

- The pinned dbt 1.11.17 CLI accepted `dbt docs generate --no-compile --empty-catalog --static`. Using it after offline parse exited 0 and created `target/index.html` and `target/static_index.html`; the manifest contains both the mart and exposure. `target/catalog.json` is intentionally empty, so the site has no warehouse column metadata. The artifact is ignored/local and was not published to Pages.
- No `.github/workflows/**` edits or GitHub Pages setting change were made; the integrator owns the Pages workflow and G7 action.

### Validation evidence

- `dbt parse --project-dir dbt/dataforge --profiles-dir dbt/dataforge --target offline --no-send-anonymous-usage-stats --no-version-check --no-partial-parse` — **PASS**, exit 0, dbt Core 1.11.17 / BigQuery adapter 1.11.3.
- `dbt ls --resource-type model --select mart_weather_province_daily` — **PASS**, resolves the mart.
- `dbt ls --resource-type test --select tag:weather_mini3` — **PASS**, resolves three new singular mart data tests plus the existing weather tests.
- `dbt ls --resource-type unit_test --select test_type:unit` — **PASS**, resolves `mart_weather_calendar_windows_handle_gaps`.
- `dbt ls --resource-type source --select source:weather_mini3.weather_landing` — **PASS**, manifest shows `loaded_at_field=landed_at`, 36h/72h thresholds, and the bounded filter.
- `dbt ls --resource-type exposure --select exposure:weather_province_daily_demo` — **PASS**, resolves the exposure dependency on the mart.
- `python -m pytest dbt/dataforge/tests/test_mart_weather_province_daily.py -q` — **PASS**, 3 passed; covers the independent fixture oracle, a gapped 7-day window, a gapped 30-day window, a complete 30-day positive case, and SQL calendar-frame guards.
- Ruff 0.17.3 on the new Python fixture test — **PASS** after the recorded I001 correction.
- `git diff --check` — **PASS**. Secret scan — **PASS**, 0 findings across 505 files.
- No CI runs were created by this worker; no files were pushed.

### Boundaries / integrator follow-up

- `dbt compile`, `dbt test` (including the dbt unit test), `dbt source freshness`, live build, and warehouse catalog generation were **not run**. The checked-in README warns that BigQuery adapter compile/docs paths may connect even with the offline target; this lane received no warehouse/credential permission.
- After integration, the integrator should run exact-head CI and add the Pages workflow using either the verified no-compile/empty-catalog path or the explicitly authorized read-only CI identity for richer catalog metadata. Page publication remains pending G7.
- Freshness thresholds (36h warn / 72h error) assume the planned daily ingestion cadence; adjust if the actual schedule changes.

## RCA log

### Patch formatting failure

- Symptom: `apply_patch` rejected the first attempt to add the mart contract tests with `invalid hunk at line 21, 'group by province_id, observation_date' is not a valid hunk header`.
- Expected vs actual: the intended model/test edits were not applied; the source worktree remained unchanged by that patch.
- Reproduction: the rejected patch contained new-file lines without the required leading `+` patch marker.
- Hypotheses: patch grammar error vs path/context mismatch; the error points to a raw SQL line being read as a hunk header, supporting patch grammar error.
- Root cause: added-file content was not prefixed as additions.
- Fix: reapply with `+` before each new-file line, using separate file hunks.
- Regression guard: inspect `git diff --check`, changed paths, and final file contents before running dbt parse.

### Patch-context mismatch

- Symptom: `apply_patch` could not find the expected `calendar_windows as (` context; no file changed.
- Expected vs actual: patch assumed the CTE name began a line; actual SQL has `), calendar_windows as (` after the preceding CTE.
- Reproduction: the rejected narrow context patch.
- Hypotheses: wrong indentation vs preceding CTE punctuation; exact file readback shows the preceding `),` is part of the line.
- Root cause: patch context omitted the preceding CTE terminator.
- Fix: reapply using the exact current line and a narrow hunk.
- Regression guard: inspect the model diff and run `git diff --check`.

### Lane report patch-context failure

- Symptom: the attempted addition of the Ruff RCA was rejected because its final context line did not match; no file changed.
- Expected vs actual: patch expected `inspect git diff check, changed paths, and run dbt parse`; the report actually says `inspect the model diff and run git diff check`.
- Reproduction: the rejected `apply_patch` hunk.
- Hypotheses: concurrent file modification vs copied context mismatch; direct readback confirmed the copied context was wrong and no concurrent edit occurred.
- Root cause: the patch used an inaccurate expected line.
- Fix: append the Ruff RCA to the report file instead of replacing the existing section.
- Regression guard: read back the appended section before retrying the Ruff fix.

### Python test Ruff check

- Symptom: Ruff 0.17.3 reported `I001` at `dbt/dataforge/tests/test_mart_weather_province_daily.py:8`; the targeted pytest run passed, but the lint command exited 1.
- Expected vs actual: the new fixture-oracle test should pass the repository import-order rule; the initial import block did not satisfy Ruff.
- Reproduction: `D:\DATA_ENGINEER\DataForge\.venv\Scripts\ruff.exe check dbt/dataforge/tests/test_mart_weather_province_daily.py`.
- Hypotheses: import ordering/group formatting vs broader Ruff configuration issue; Ruff's specific `I001` diagnostic supports the import-order hypothesis.
- Root cause: the new test's import section was not normalized to the repository's Ruff/isort rules.
- Fix: inspect Ruff's suggested diff and make the minimal import-only correction.
- Regression guard: rerun that exact Ruff command and verify no test behavior changes.
