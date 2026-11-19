# Worker Q — W9-2 Quality + Observability lane

Branch: `feat/w9-q-2` from `origin/main` at `3a20050e813700cd0a050c69aa1dbd652ca9fc08`. This report covers Q1–Q6 (Q-PR1) and Q7–Q11 (Q-PR2). Q10 proceeded only after the parent confirmed W7 PR #40 S12 merged at `4b0cdd9`; the Airflow gate remains disabled by default, and Airflow behavior is **UNVERIFIED** pending exact-head CI. Q8 Monitoring HCL is authored for review but unplanned and unapplied. No Terraform plan/apply, GCP dataset/table write, image build, deployment, or production write was performed. One bounded public Open-Meteo GET was captured as a test fixture and documented.

## Q-PR1 status (Q1–Q6)

Q1–Q6 have local implementations and fixture/configuration evidence. Q2 adds the cataloged F10 test, annotates the existing F02 defense, and adds blocking unique/not-null tests for the two baseline keys. Tests for G's two new privacy models are deferred to Q-PR2 after G-PR1 merges, preserving the required PR order. O1 has provisioned `w9_drill` and `dataforge_dq`, but they are empty; F07/F10 remain unverified because no isolated weather landing table/data or live dbt/BigQuery run exists. Q-PR1 #44 merged normally at `659ba8a` after the exact-head runs listed below passed.

## Changed files

- G1/DQ: `quality/gx/weather_landing.yml`; `src/dataforge/dq/{__init__.py,__main__.py,gate.py,results.py,wap.py}`.
- G0: `cloud/jobs/week7_weather/validation.py`, `cloud/jobs/week7_weather/weather_job.py`, and the optional response-validator callback in `src/dataforge/weather.py`. The parent explicitly authorized the `weather.py` callback as a scoped exception.
- G2: `dbt/dataforge/models/week9_tests.yml`; `dbt/dataforge/macros/dq_float_equal.sql`, `dq_pk_tests.sql`, `dq_write_results.sql`; `dbt/dataforge/tests/assert_week9_rain_precip_consistency.sql`; severity/metadata for the existing F02 defense in `dbt/dataforge/tests/assert_mini3_weather_grains_unique.sql`.
- CI dependency fix: `pyproject.toml` and `requirements-py311.lock` add the ADR-pinned GX Core dependency.
- Local fault harness/evidence: `scripts/week9_fault_inject.py`; `tests/week9/test_gate.py`, `test_weather_validation.py`, `test_model_pk_config.py`, `test_results.py`, `test_wap.py`; `tests/week9/faults/cases.py`, `manifest.yml`, the captured 7-date Parquet fixture, and the captured Open-Meteo JSON plus metadata; `tests/week9/fault_matrix_report.md`; local quarantine evidence under `tests/week9/evidence/`.
- Runbook and lane report: `docs/week9/runbooks/quarantine-release.md`, this file.

No existing `models/sources.yml`, `models/schema.yml`, or `models/weather/marts/schema.yml` was edited. No fault-catalog IDs were changed.

## Q1 — G1 landing gate

`python -m dataforge.dq gate --layer landing --dataset <ds> --date <YYYY-MM-DD>` runs GX Core 1.25.0 expectations over a Pandas frame read from `<project>.<dataset>.weather_landing`. The code restricts reads to project `dataforge-p7-lab-d0f725` and datasets `w9_drill` / `dbt_ci_pr_*`; the query caps `maximum_bytes_billed` at 1 GiB. `DQ_ENFORCE=warn` records without blocking; `DQ_ENFORCE=block` exits nonzero on P1 failures. No BigQuery connection or connector test was run.

Catalog checks implemented: `G1.LANDING.SCHEMA`, `G1.LANDING.SCHEMA_ADDITIVE`, `G1.LANDING.PROVINCE_ID_NOT_NULL`, `G1.LANDING.GRAIN_UNIQUE`, `G1.LANDING.PHYSICAL_RANGE`, `G1.LANDING.PROVINCE_DOMAIN`, `G1.LANDING.ROWS_PER_DATE`, `G1.LANDING.NO_FUTURE_DATE`, and `G1.LANDING.TEMP_UNIT_RANGE`. F07 freshness remains owned by `G2.SOURCE.FRESHNESS`, per the catalog and integrator direction; it is not duplicated in GX.

The contract sets the physical temperature range to −90..70 °C. F12's 80..100 °C semantic signal overlaps that upper bound: F12 values fail both physical range and temp-unit checks. Both catalog IDs are kept, with `TEMP_UNIT_RANGE` the expected F12 detector. F03's `temp_max_c=99` also trips the unit heuristic while its negative precipitation independently trips `PHYSICAL_RANGE`.

## Q2 — G2 dbt checks

`G2.WEATHER.RAIN_PRECIP_CONSISTENCY` is a blocking singular test in `dbt/dataforge/tests/assert_week9_rain_precip_consistency.sql`, with `tier_blocking`, P1/error thresholds and environment-gated `store_failures`. It uses `dq_float_equal` instead of exact FLOAT64 equality. Keeping it singular avoids a duplicate `mart_weather_province_daily` schema patch in the existing G-owned YAML. The existing `G2.WEATHER.GRAIN_UNIQUE` silver/gold defense is now tagged P1 and carries its catalog metadata. The new `week9_tests.yml` adds blocking `not_null` + `unique` tests for `stg_week5_run_events.event_id` and `stg_week5_pipeline_checkpoints.source_id`, using stable `G2.MODEL.*` IDs without changing the fault catalog. `dq_pk_tests.sql` gates their `store_failures` on `DATAFORGE_DQ_RESULTS_ENABLED`. `tests/week9/test_model_pk_config.py` verifies these two configurations. A post-parse manifest audit found **16/16 base models** have a uniqueness check on the declared single/composite grain plus not-null tests for each key column; the two new baseline pairs close the prior gaps. Tests for `stg_customer_profile_restricted.fixture_id` and `dim_customer_profile_safe.customer_token` are intentionally deferred to Q-PR2 after G-PR1 merges; the PII model tests must store only the authorized synthetic keys in `dataforge_dq`. Actual dbt test execution remains unverified.

| Key/grain category | Models covered | Complete unique + key not-null pairs |
|---|---:|---:|
| Single-column keys | 12 | 12/12 |
| Composite weather grains | 4 | 4/4 |
| **Total base models** | **16** | **16/16** |

The composite pairs use the existing singular grain tests plus not-null tests on each grain column: `stg_weather_mini3_landing`, `int_weather_daily`, `fct_mini3_weather_daily`, and `mart_weather_province_daily`.

Existing relationship, accepted-value, and other key tests in model YAML were left intact. There are also preexisting dbt landing tests, `assert_mini3_weather_landing_request_keys.sql` and `assert_mini3_weather_metric_ranges.sql`, that overlap G1 checks; integrator should reconcile their ownership before claiming the one-owner map is complete. `assert_mart_weather_province_daily_grain_unique.sql` is another preexisting grain assertion outside the catalog mapping.

## Q3/Q4 — G0 and `dq_results`

One bounded, read-only request captured a real HCM Open-Meteo ERA5 response for 2026-11-05. Raw bytes, source URL, capture time, response SHA-256, attribution and CC BY 4.0 metadata are saved at `tests/week9/faults/captures/`. Response SHA-256: `bf203c6bd2d78b87e0c451a414371abbdddf051204c5f32cfd77d5f4b3f261e6` (354 bytes). The separate landing-slice fixture is a recorded 21-row, seven-date capture with SHA-256 `ad79df00245dcdd0a909e08093fe70e02c07884e65dce445d2f3dc5f9114e798`.

`validation.py` validates response shape, `daily_units`, timezone and exact requested-date coverage before `parse_daily` runs. F05a/F11 mutations in the unit tests derive from the captured response; F-T1 uses a simulated 503 followed by that captured successful body. The W7 job records G0 pass/fail summaries only when `DATAFORGE_DQ_RESULTS_ENABLED=true`; it is off by default. This avoids enabling DQ writes for the existing W7 deployment path.

The Python and dbt writers use the `dataforge_dq.dq_results` schema (`run_id, check_id, layer, severity, status, observed, threshold, failing_rows, contract_version, ts`); first write creates a day-partitioned table. G0, F02/F10 `store_failures`, the generic PK test macros, and the dbt `on-run-end` writer all require `DATAFORGE_DQ_RESULTS_ENABLED=true`; the default is false. The root integrator added the hook to `dbt_project.yml` in the local Q-PR1 integration branch:

```yaml
on-run-end:
  - "{{ dq_write_run_results(results) }}"
```

The integrator also added `generate_schema_name.sql` to route `dataforge_dq`, `pii_safe`, and `restricted_pii` to their exact datasets while preserving dbt's existing `<target>_<custom_schema>` naming for every other schema. An offline `dbt parse` with `DATAFORGE_DQ_RESULTS_ENABLED=false` passed; the parsed manifest resolves baseline PK `store_failures` to boolean `false` and their test schema to `dataforge_dq`. No warehouse connection was made.

```jinja
{% macro generate_schema_name(custom_schema_name, node) -%}
    {% if custom_schema_name is none %}
        {{ target.schema }}
    {% elif custom_schema_name | trim == 'dataforge_dq' %}
        dataforge_dq
    {% else %}
        {{ target.schema }}_{{ custom_schema_name | trim }}
    {% endif %}
{%- endmacro %}
```

The existing W7 weather-job Dockerfile also needs these copies before this call path can run in that image; this lane did not build or edit the image. O4 should set `DATAFORGE_DQ_RESULTS_ENABLED=true` only for the W9 isolated runtime, after `dataforge_dq` is provisioned:

```dockerfile
COPY cloud/jobs/week7_weather/validation.py /app/cloud/jobs/week7_weather/validation.py
COPY src/dataforge/dq/__init__.py /app/src/dataforge/dq/__init__.py
COPY src/dataforge/dq/results.py /app/src/dataforge/dq/results.py
```

For the W9 isolated runtime, set `DATAFORGE_DQ_RESULTS_ENABLED=true` only after the permitted datasets and identities exist. No such runtime was started.

## Q5 — Check IDs and fixture evidence

| Fault | Expected check ID | Local fixture/action evidence |
|---|---|---|
| F01 | `G1.LANDING.PROVINCE_ID_NOT_NULL` | Null province mutation; P1 quarantine |
| F02 | `G1.LANDING.GRAIN_UNIQUE` primary; `G2.WEATHER.GRAIN_UNIQUE` defense | Duplicate one row while preserving three rows/date; G1 P1 quarantine. G2 test is implemented but dbt execution is unverified. |
| F03 | `G1.LANDING.PHYSICAL_RANGE` | `temp_max_c=99`, `precipitation_mm=-5`; P1 quarantine |
| F04 | `G1.LANDING.PROVINCE_DOMAIN` | Province changed to `SG`; P1 quarantine |
| F05a | `G0.API.SCHEMA` and `G1.LANDING.SCHEMA` | Captured response unit mutation plus landing required-column removal; P1 block |
| F05b | `G1.LANDING.SCHEMA_ADDITIVE` | Added nullable field; P2 warn/publish |
| F06 | `G1.LANDING.ROWS_PER_DATE` | One province removed; P1 quarantine |
| F07 | `G2.SOURCE.FRESHNESS` | **UNVERIFIED**; datasets exist but are empty, with no isolated `weather_landing` table/data or live source-freshness run |
| F08 | `G1.LANDING.NO_FUTURE_DATE` | All three rows for one date moved into the future; P1 quarantine |
| F09 | `G1.LANDING.IDEMPOTENCY_REPLAY` | Identical captured candidate hash; severity None, no-op, unchanged Gold hash |
| F10 | `G2.WEATHER.RAIN_PRECIP_CONSISTENCY` | **UNVERIFIED**; datasets exist but contain no isolated weather fixture, and no live dbt/BigQuery test ran |
| F11 | `G0.API.RESPONSE_COMPLETENESS` | Empty arrays / missing requested dates derived from the captured 200 response; block before landing |
| F12 | `G1.LANDING.TEMP_UNIT_RANGE` | Temperature changed to 90 °C; unit and physical checks both fail; P1 quarantine |
| F-T1 | `G0.API.TRANSIENT_RETRY` | One synthetic 503 followed by captured response; retry succeeds, no P1 alert |
| F-N0 | `ALERTING.NEGATIVE_CONTROL` | Clean captured landing frame: zero P1/P2 failures or warnings, no local alert attempt |

`tests/week9/fault_matrix_report.md` contains 13 PASS and 2 UNVERIFIED rows. The matrix command returns exit 1 intentionally because F07 and F10 are not green; the report does not relabel them as not applicable. No alert channel was attempted. “Zero alerts” here only describes the local harness, not live Monitoring/Slack/email delivery.

## Q6 — Local Write-Audit-Publish evidence

The file-based WAP harness snapshots the last-good Parquet, writes a quarantined candidate plus a manifest reason on P1, compares the Gold hash before/after, and exposes `python -m dataforge.dq.wap release ...` for a deliberate re-audit after correction. The runbook is `docs/week9/runbooks/quarantine-release.md`. A persistent F01 local fixture is at `tests/week9/evidence/w9_drill/`; its manifest records `G1.LANDING.PROVINCE_ID_NOT_NULL` and confirms the before/after Gold SHA-256 both equal `ad79df00245dcdd0a909e08093fe70e02c07884e65dce445d2f3dc5f9114e798`. The release path is unit-tested, but no live BigQuery WAP, quarantine, or release occurred.

## Verification commands and outcomes

### Q-PR1 exact-head CI RCA

Runs `44361556271`, `44361676034`, `44361676432`, and `44361676242` failed. The failing steps were the offline suite and lint; Pages passed. The offline suite could not find `tests/week9/faults/weather_7date_slice.parquet` because `.gitignore:48` ignores `*.parquet`. The existing file's SHA-256 was verified as `ad79df00245dcdd0a909e08093fe70e02c07884e65dce445d2f3dc5f9114e798` (10,160 bytes) and it is now force-tracked without changing its bytes. The offline suite also failed to import `great_expectations` from the DQ gate because GX was missing from the dev extra and Python 3.11 constraints; Q added the ADR-pinned 1.25.0 package to both.

SQLFluff 3.4.2 flagged LT05 on the `dq_float_equal` macro signature and unresolved `env_var` / `dq_float_equal` references plus LT02/PRS in the F10 singular test. I wrapped the macro and config expression, and put the predicate on its own line with four-space continuation indentation; the predicates and thresholds are unchanged. The integrator added the shared SQLFluff dbt/Jinja configuration in commit `7f08a3d`. No CI rerun has been performed after these changes; do not treat this as green.

- `pytest tests/week9 -q` in the existing GX 1.25.0 Python 3.12 venv with the local pytest/PyYAML user-site path appended: **31 passed**. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` avoids an unrelated global `dash` plugin import; no packages were installed.
- `ruff check cloud/jobs/week7_weather/validation.py cloud/jobs/week7_weather/weather_job.py src/dataforge/weather.py src/dataforge/dq tests/week9 scripts/week9_fault_inject.py`: **passed**.
- `python -m compileall -q src/dataforge/dq cloud/jobs/week7_weather/validation.py cloud/jobs/week7_weather/weather_job.py src/dataforge/weather.py tests/week9 scripts/week9_fault_inject.py`: **passed**.
- PyYAML parse of `quality/gx/weather_landing.yml`, `dbt/dataforge/models/week9_tests.yml`, and `tests/week9/faults/manifest.yml`: **passed**.
- Jinja syntax parse of both `dq_*.sql` macros: **passed** (not a dbt invocation).
- `dbt parse --no-partial-parse --project-dir D:\DATA_ENGINEER\DataForge_w9_q\dbt\dataforge --profiles-dir D:\DATA_ENGINEER\_tmp\w9_q_dbt_profile_20261118 --target offline` with pinned dbt-core 1.11.17 / dbt-bigquery 1.11.3: **passed** with the flag unset and with `DATAFORGE_DQ_RESULTS_ENABLED=true`; manifest `store_failures` values were bool `False` by default and bool `True` when enabled for F02, F10, and the four baseline PK tests. No warehouse connection was made. `dbt build` and live result-hook execution remain **UNVERIFIED**.
- Lock refresh method: `uv pip compile pyproject.toml --extra dev --extra powerbi --extra gcp --python-version 3.11 --constraint requirements-py311.lock --no-emit-package dataforge-vn-commerce --output-file requirements-py311.generated.lock`. The output preserved all 25 prior package pins and resolved 65 additional direct/transitive pins (90 total); it was reviewed and promoted to `requirements-py311.lock`. No package was installed. The lock is used as a CI constraints file.
- The temporary profile at `D:\DATA_ENGINEER\_tmp\w9_q_dbt_profile_20261118\profiles.yml` is a copy of `profiles.example.yml` with the offline target (`dataforge-offline-project`) and no credentials. Automatic review rejected my cleanup command; I did not retry, so the temporary profile directory remains.
- Existing `pytest tests/mini3_api/test_weather_job.py -q` in the pinned W9 Python 3.12.13 environment: **11 passed**. An earlier system-Python attempt had 2 import errors for missing `google.cloud.bigquery`; no packages were installed, and the pinned-environment rerun supersedes that mismatch.
- Q-PR1 exact-head runs on `97080a87` all passed: DataForge push `44370690828`, DataForge PR `44370708719`, Week 7 `44370708289`, Pages `44370708248`, and Week 9 DataOps `44370708408` (including Gitleaks and toolbox smoke). PR #44 merged at `659ba8a`. The failed runs above were corrected by tracking the fixture, pinning GX for dev CI, and fixing SQLFluff/Jinja config and layout.
- A later G-PR1 parse found the Q test entries duplicated G's existing schema entries. The integrator moved those two test blocks into the G-owned `models/schema.yml` with check IDs/thresholds unchanged, removed `week9_tests.yml`, and updated the Q key-config test path. G-PR1 exact-head CI is handling that integration.

## Integrator actions

1. The integrator added the Dockerfile copies above so a future authorized image can import G0 validation and the DQ results sink. No image was built, pushed, or deployed. Set `DATAFORGE_DQ_RESULTS_ENABLED=true` only in the W9 isolated job environment.
2. The integrator added `dq_write_run_results(results)` in `dbt_project.yml` and the exact `dataforge_dq` schema routing; before cloud execution, verify the result writer against the provisioned isolated dataset.
3. After G-PR1 merges, add the restricted/safe customer PK tests in Q-PR2, keeping their failure rows limited to authorized synthetic identifiers.
4. Reconcile the preexisting landing-range/key dbt tests with the G1 owner map and the F02 G2 defense.
5. With O1 datasets now provisioned but empty, after an authorized weather landing table/clean slice and WIF identity are available, verify the G1 BigQuery source path and result writer, run dbt build, execute F07/F10 on isolated fixtures, and record exact-head CI run IDs.

## Q-PR2 checkpoint — Q7 monitors and Q8 alert-routing core

Branch: `feat/w9-q-2` from `origin/main` at `3a20050e813700cd0a050c69aa1dbd652ca9fc08`. This first bounded Q-PR2 slice implements the local code path; Terraform and Airflow follow in separate commits.

- `src/dataforge/dq/observability.py` reads persisted `dq_results`, compares `INFORMATION_SCHEMA.COLUMNS` with the weather contract, and queries two 30-day distribution windows. It maps existing G1/G2 results to `DQ_GATE_FAILED`, `SCHEMA_DRIFT`, `FRESHNESS_BREACH`, `VOLUME_ANOMALY`, and `DQ_HEARTBEAT` events without rerunning gate logic. Distribution signals are P2 only and require at least 20 observations in each window. `max(landed_at)` is context only; F07 thresholds stay with G2/source freshness.
- `src/dataforge/dq/notifications.py` provides P1/P2 Slack routing, P3 digest collection, `(check_id, date)` deduplication, and resolve messages. Webhook reads, `dataforge_dq.alert_state` access, and `CloudLoggingEventSink` writes happen only on explicit opt-in; no secret or cloud sink was accessed. P3 currently returns a digest for an integrator-owned scheduled delivery path.
- G1/G0/dbt results carry non-sensitive dataset/date/publish context in `observed`, allowing event scope and impact without changing `dq_results` columns. The G0 weather-job change is limited to its Q-owned result-persistence call site and runs only when `DATAFORGE_DQ_RESULTS_ENABLED=true`.
- Check IDs surfaced in this slice: `G1.LANDING.SCHEMA` and `G1.LANDING.SCHEMA_ADDITIVE` map to `SCHEMA_DRIFT`; `G1.LANDING.ROWS_PER_DATE` maps to `VOLUME_ANOMALY`; `G2.SOURCE.FRESHNESS` maps to `FRESHNESS_BREACH`; the monitor adds `MONITOR.WEATHER.TEMP_DISTRIBUTION` and `ALERTING.DQ_HEARTBEAT`. Other recorded gate failures retain their original check IDs under `DQ_GATE_FAILED`; the fault catalog was not changed.
- The monitor CLI is `python -m dataforge.dq monitor --dataset <isolated-dataset> --date <YYYY-MM-DD>`; it accepts only `w9_drill` or `dbt_ci_pr_*`. `--emit-logs` and `--send-alerts` are explicit opt-ins. No monitor command was run against BigQuery.
- Files in this checkpoint: `cloud/jobs/week7_weather/weather_job.py`, `dbt/dataforge/macros/dq_write_results.sql`, `src/dataforge/dq/{__main__,gate,notifications,observability,results,wap}.py`, `tests/week9/{test_gate,test_notifications,test_observability,test_results}.py`, and this report.
- Local checks: the seven explicit Q-owned test modules (`test_gate.py`, `test_model_pk_config.py`, `test_results.py`, `test_wap.py`, `test_weather_validation.py`, `test_observability.py`, `test_notifications.py`) **41 passed** using the existing GX 1.25.0 venv, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, and the installed user-site path; no packages were installed. `ruff check src/dataforge/dq cloud/jobs/week7_weather/validation.py cloud/jobs/week7_weather/weather_job.py src/dataforge/weather.py tests/week9 scripts/week9_fault_inject.py`, `python -m compileall -q src/dataforge/dq cloud/jobs/week7_weather/weather_job.py`, and `git diff --check` **passed**. No new CI or live-GCP run IDs exist. The provisioned W9 datasets remain empty, and GCP auth is expired.

The parent confirmed W7 PR #40 (S12–S14) merged at `4b0cdd9`, so Q10 may proceed under the S12 gate. This checkpoint does not change the Airflow DAG/harness, W7 resources, or CI workflow. Q8 HCL is added in the next local checkpoint; Q9 runbooks and Q10 gated Airflow harness remain. No Terraform plan/apply, GCP access, image build, push, or deployment was performed.

## Q-PR2 checkpoint 2 — Q8 Monitoring HCL

Files: `cloud/terraform/week9_dataops/metrics.tf`, `alerts.tf`, `variables.tf`, `outputs.tf`, `docs/week9/q8-terraform-plan.md`, and this report. HCL is scoped only to the existing Week 9 Terraform root; no W7 Terraform/resource file changed.

- Five conditional log metrics cover `DQ_GATE_FAILED`, `SCHEMA_DRIFT`, `FRESHNESS_BREACH`, `VOLUME_ANOMALY`, and `DQ_HEARTBEAT`. Filters require the `dataforge-week9-dq` structured log and allow only `w9_drill` / `dbt_ci_pr_*` datasets, matching the DQ code allowlist; metric labels are `severity` and `status`.
- Three P1 policies send Monitoring email through the supplied existing C9 channel for P1/FAIL gate, schema, and volume events. The freshness policy is separately gated by `enable_dq_freshness_alert=false` so the intentionally stopped W7 pipeline does not open daily incidents; planned pauses use a time-bounded Cloud Monitoring snooze. P2 remains Slack-only through the Q8 router; P3 remains digest-only. The fifth policy watches for a 23.5-hour heartbeat absence and has `enabled=false` by default (`enable_dq_deadman=false`). `enable_dq_alerting=false` defaults all metrics and policies to absent. The 23.5-hour threshold is Cloud Monitoring's documented maximum, and absence evaluation requires an initial heartbeat data point.
- `docs/week9/q8-terraform-plan.md` is the separate integrator review plan. Terraform plan/apply and live evidence are **UNVERIFIED**; the integrator's GCP authorization is expired. Local shell lookup found neither `terraform` nor `tofu`, so no HCL CLI validation could run. No cloud command was attempted.
- Static `git diff --check` is the only check on this HCL slice; no new CI run IDs exist. Costs, actual C9 channel name, live structured-log shape, and policy behavior remain unverified. Monitoring absence evaluation will also need a first heartbeat time series.
- Integrator actions: obtain the existing C9 channel resource name without creating a duplicate; restore authorization; run an exact-head Terraform plan and review resource diffs before any apply; confirm live event labels and the Q9 runbook links; keep the heartbeat alert disabled until a schedule and maintenance window exist.

## Q-PR2 checkpoint 3 — Q9 runbooks

Files: `docs/week9/runbooks/DQ_GATE_FAILED.md`, `SCHEMA_DRIFT.md`, `FRESHNESS_BREACH.md`, `VOLUME_ANOMALY.md`, `DQ_HEARTBEAT.md`, and this report.

- The runbooks cover event/check IDs `DQ_GATE_FAILED` (catalog-owned checks), `G1.LANDING.SCHEMA`, `G1.LANDING.SCHEMA_ADDITIVE`, `G2.SOURCE.FRESHNESS`, `G1.LANDING.ROWS_PER_DATE`, `MONITOR.WEATHER.TEMP_DISTRIBUTION`, and `ALERTING.DQ_HEARTBEAT`. They include safe summary/metadata queries, severity and publish impact, rerun/backfill/quarantine-release/contract-fix/do-nothing decisions, escalation, and rollback boundaries.
- Freshness and heartbeat procedures keep their policies disabled while the W7 pipeline is intentionally stopped; an activated policy uses a time-bounded Monitoring snooze for planned maintenance. The heartbeat stays disabled by default and requires a first sample before absence detection.
- Focused documentation check: all 5 runbooks contain the required symptom, triage, decision, escalation/rollback sections; all local Markdown links resolve. `git diff --check` passed. No software tests, cloud calls, or alert drills were run.
- No CI run IDs exist. Live query validity against an isolated populated dataset, Slack/email delivery, and MTTD remain **UNVERIFIED**; F07/F10 remain unverified as recorded in the fault matrix.
- Integrator actions: validate the summary queries against a populated authorized `w9_drill` or `dbt_ci_pr_*` dataset; verify C9/Slack routes and runbook links after restoring credentials; capture injection and delivered timestamps for an authorized MTTD drill. No production write is authorized here.

## Q-PR2 checkpoint 4 — Q10 gated Airflow reference and Q11 heartbeat

S12 was confirmed merged by the parent at W7 PR #40 (`4b0cdd9`), so Q10 proceeded. Files: `labs/airflow_reference/dags/dataforge_week7_weather_cloud.py`, `labs/airflow_reference/harness/dags/dataforge_week7_airflow_retry_harness.py`, `labs/airflow_reference/harness/run_scheduler_harness.py`, `labs/airflow_reference/tests/test_week7_weather_dag_contract.py`, `labs/airflow_reference/tests/test_week9_quality_gate_contract.py`, `labs/airflow_reference/README.md`, `docs/week9/runbooks/DQ_GATE_FAILED.md`, and this report. No `cloud/terraform/`, `cloud/jobs/`, or W7 resource files changed.

- `quality_gate_landing` is between landing reconciliation and `dbt_weather_build`. `DATAFORGE_DQ_GATE_ENABLED` defaults false and logs a disabled status without creating a client. The W7 Airflow runtime has no live isolated W9 adapter; if enabled without one, it fails closed before dbt.
- The scheduler harness adds `dq_gate_disabled`, `dq_gate_pass`, and `dq_gate_fail` scenarios. Pass/fail use a test-only adapter scoped to `w9_drill`; the P1 fixture uses existing check ID `G1.LANDING.PHYSICAL_RANGE`. The no-adapter sentinel `ALERTING.DQ_GATE_ADAPTER_UNAVAILABLE` is a control-plane status, not a catalog change. The local callback emits `DQ_GATE_FAILED` summary metadata and the runbook URL. The failure assertion requires `dbt_weather_build=upstream_failed` and zero dbt build submissions. No fault-catalog IDs were changed.
- Q11's `ALERTING.DQ_HEARTBEAT` absence policy is included in Q8 `alerts.tf`, disabled by default, with the 23.5-hour upper-limit window and maintenance-window guard; the Q9 heartbeat runbook documents the first-sample caveat. No schedule or live policy was enabled.
- Local checks: targeted Ruff **passed**, `compileall` **passed**, `git diff --check` **passed**. Airflow is absent from the local Python environment; local Docker is prohibited for this lane, so neither Airflow unit tests nor the scheduler harness ran. No CI run IDs exist. Existing `.github/workflows/week7-ci.yml` already path-triggers on `labs/airflow_reference/**` and runs `ci.ps1 -Scenario scheduler_harness`; no workflow edit was needed.
- Risks: this is a test-only W9 gate seam, not a live G1 adapter. Setting the flag in the W7 runtime without an adapter intentionally fails closed. Airflow scheduler behavior and the three new scenarios still need exact-head CI evidence.
- Integrator actions: run the existing Week 7 Airflow CI job on the exact head; verify the gate-failure callback and DBT blocking evidence; keep `DATAFORGE_DQ_GATE_ENABLED` unset/false in W7 runtime; do not add W7 GCP resources. Terraform plan/apply and live Monitoring evidence remain **UNVERIFIED** pending authorization.

## Q follow-up — GX 1.25 / Pandas 3 schema RCA

Files in the Q follow-up: `quality/gx/weather_landing.yml`, `src/dataforge/dq/gate.py`, `tests/week9/test_gate.py`, and this report.

RCA for O-PR2 toolbox CI run `44418972138` (head `7015e9066143b2967af2b3535258a2d1b70b940f`): the offline test step had **6 failed / 44 passed**. All six failures were clean G1/WAP paths cascading from `G1.LANDING.SCHEMA` (`failing_rows=6`); WAP behavior was not the cause. The exact toolbox lock pins Great Expectations 1.25.0, Pandas 3.1.1, and PyArrow 26.0.1. Under Pandas 3.1.1, the six physical STRING fields (`province_id`, `source`, `model`, `request_id`, `source_sha256`, `manifest_uri`) load as Pandas `str`, while the schema config expected exact dtype `object`. GX `ExpectColumnTypeToBe` is exact-dtype, so it rejected valid strings. `observation_date`, numeric fields, and `landed_at` were not implicated.

`quality/gx/weather_landing.yml` now declares those six as logical `str` values. The gate uses GX `ExpectColumnValuesToBeOfType(type_="str")` for them, so non-null values must be strings under Pandas 2 object and Pandas 3 string representations. The ODCS-required string fields (`request_id`, `source`, `model`, `source_sha256`, `manifest_uri`) also reject nulls under the existing `G1.LANDING.SCHEMA` check. `G1.LANDING.PROVINCE_ID_NOT_NULL` still exclusively owns province nulls, and nullable precipitation/temperature remain allowed. Numeric/date/timestamp type assertions remain exact; mixed object columns containing an integer fail the P1 schema check. No catalog IDs or WAP assertions changed.

- Focused tests added: three Pandas string representations (`object`, `str`, `string`), a mixed-object non-string rejection, required-string null rejection, F01 province-null ownership, and nullable weather metric values. All five required STRING fields reject null under `G1.LANDING.SCHEMA`; F01 remains under its existing dedicated check.
- Reproduction command source: `gh run view 44418972138 --log-failed`. Local lock reproduction: `uv venv --python D:\DATA_ENGINEER\_tmp\w9_spikes\gx\.venv\Scripts\python.exe D:\DATA_ENGINEER\_tmp\w9_q_toolbox_repro_44418972138`, then `uv pip sync --python D:\DATA_ENGINEER\_tmp\w9_q_toolbox_repro_44418972138\Scripts\python.exe --require-hashes D:\DATA_ENGINEER\_tmp\w9_toolbox_exact_7015_requirements.lock`; that temporary requirements file came from `git show 7015e9066143b2967af2b3535258a2d1b70b940f:deploy/dataops_toolbox/requirements.lock`.
- Reproduced before the fix in a temporary Python 3.12.13 venv synchronized from the exact O-PR2 `deploy/dataops_toolbox/requirements.lock` with `--require-hashes`; the clean and additive tests failed as in CI. The lock supplied GX 1.25.0 / Pandas 3.1.1 / PyArrow 26.0.1 and pytest 8.4.2. The CI Dockerfile uses Python 3.12.12; this local reproduction differed only by Python patch version. No Docker, cloud, or GCP call was used.
- After the fix, `PYTHONPATH=src; PYTEST_DISABLE_PLUGIN_AUTOLOAD=1; python -m pytest -q -p no:cacheprovider tests/week9` in the exact locked venv: **63 passed**. The seven Q-owned modules in the GX 1.25.0 / Pandas 2.3.3 venv: **52 passed**. Targeted Ruff, `python -m compileall -q src/dataforge/dq/gate.py tests/week9/test_gate.py`, PyYAML parse, and `git diff --check` also passed.
- O-PR2 DataForge CI run `44423313989` separately failed Ruff F821 because its cherry-picked test file referenced `json.loads` without carrying the Q branch's pre-existing import. This follow-up uses a self-contained `_result_observed()` helper with a local JSON import and keeps the parsed `issues` assertions exact. Ruff and the focused locked-toolbox gate tests now pass (**23 passed**). No post-fix CI run ID exists yet.
- Integrator action: cherry-pick this Q follow-up commit into O-PR2, rerun exact-head toolbox CI, and confirm the required-string nulls and six downstream WAP cases pass. The toolbox's Pandas 3.1.1 lock differs from `pyproject.toml`'s project extra bound (`pandas<3`); this Q fix supports both representations, but the lock/version policy remains for O/integrator review.
