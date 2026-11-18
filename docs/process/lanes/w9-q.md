# Worker Q — W9-2 Quality + Observability lane

Branch: `feat/w9-q-1` from `origin/main` at `ab345f7`. Scope stopped at Q1–Q6 / Q-PR1; Q7–Q11 remain a later lane. No Terraform/API enablement, GCP dataset/table write, image build, deployment, or production write was performed. One bounded public Open-Meteo GET was captured as a test fixture and documented.

## Status

Q1–Q6 have local implementations and fixture/configuration evidence. Q2 adds the cataloged F10 test, annotates the existing F02 defense, and adds blocking unique/not-null tests for the two baseline keys. Tests for G's two new privacy models are deferred to Q-PR2 after G-PR1 merges, preserving the required PR order. F07 and F10 could not be exercised against dbt/BigQuery because no isolated W9 dataset exists. Q-PR1 CI and exact-head run IDs are **UNVERIFIED**; GitHub access was blocked at `github.com:443`.

## Changed files

- G1/DQ: `quality/gx/weather_landing.yml`; `src/dataforge/dq/{__init__.py,__main__.py,gate.py,results.py,wap.py}`.
- G0: `cloud/jobs/week7_weather/validation.py`, `cloud/jobs/week7_weather/weather_job.py`, and the optional response-validator callback in `src/dataforge/weather.py`. The parent explicitly authorized the `weather.py` callback as a scoped exception.
- G2: `dbt/dataforge/models/week9_tests.yml`; `dbt/dataforge/macros/dq_float_equal.sql`, `dq_pk_tests.sql`, `dq_write_results.sql`; `dbt/dataforge/tests/assert_week9_rain_precip_consistency.sql`; severity/metadata for the existing F02 defense in `dbt/dataforge/tests/assert_mini3_weather_grains_unique.sql`.
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

The Python and dbt writers use the `dataforge_dq.dq_results` schema (`run_id, check_id, layer, severity, status, observed, threshold, failing_rows, contract_version, ts`); first write creates a day-partitioned table. G0, F02/F10 `store_failures`, the generic PK test macros, and the dbt `on-run-end` writer all require `DATAFORGE_DQ_RESULTS_ENABLED=true`; the default is false. The hook is in an integrator-owned file and was not added here:

```yaml
on-run-end:
  - "{{ dq_write_run_results(results) }}"
```

dbt's default custom-schema naming may prefix `dataforge_dq` with the target dataset, which would defeat the requested dedicated dataset. Integrator should special-case this schema in `generate_schema_name` while preserving the current default for all other schemas, or choose another reviewed destination. Example special case:

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
| F07 | `G2.SOURCE.FRESHNESS` | **UNVERIFIED**; needs isolated dbt source-freshness execution |
| F08 | `G1.LANDING.NO_FUTURE_DATE` | All three rows for one date moved into the future; P1 quarantine |
| F09 | `G1.LANDING.IDEMPOTENCY_REPLAY` | Identical captured candidate hash; severity None, no-op, unchanged Gold hash |
| F10 | `G2.WEATHER.RAIN_PRECIP_CONSISTENCY` | **UNVERIFIED**; requires G2 test against an isolated dbt dataset |
| F11 | `G0.API.RESPONSE_COMPLETENESS` | Empty arrays / missing requested dates derived from the captured 200 response; block before landing |
| F12 | `G1.LANDING.TEMP_UNIT_RANGE` | Temperature changed to 90 °C; unit and physical checks both fail; P1 quarantine |
| F-T1 | `G0.API.TRANSIENT_RETRY` | One synthetic 503 followed by captured response; retry succeeds, no P1 alert |
| F-N0 | `ALERTING.NEGATIVE_CONTROL` | Clean captured landing frame: zero P1/P2 failures or warnings, no local alert attempt |

`tests/week9/fault_matrix_report.md` contains 13 PASS and 2 UNVERIFIED rows. The matrix command returns exit 1 intentionally because F07 and F10 are not green; the report does not relabel them as not applicable. No alert channel was attempted. “Zero alerts” here only describes the local harness, not live Monitoring/Slack/email delivery.

## Q6 — Local Write-Audit-Publish evidence

The file-based WAP harness snapshots the last-good Parquet, writes a quarantined candidate plus a manifest reason on P1, compares the Gold hash before/after, and exposes `python -m dataforge.dq.wap release ...` for a deliberate re-audit after correction. The runbook is `docs/week9/runbooks/quarantine-release.md`. A persistent F01 local fixture is at `tests/week9/evidence/w9_drill/`; its manifest records `G1.LANDING.PROVINCE_ID_NOT_NULL` and confirms the before/after Gold SHA-256 both equal `ad79df00245dcdd0a909e08093fe70e02c07884e65dce445d2f3dc5f9114e798`. The release path is unit-tested, but no live BigQuery WAP, quarantine, or release occurred.

## Verification commands and outcomes

- `pytest tests/week9 -q` in the existing GX 1.25.0 Python 3.12 venv with the local pytest/PyYAML user-site path appended: **31 passed**. `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` avoids an unrelated global `dash` plugin import; no packages were installed.
- `ruff check cloud/jobs/week7_weather/validation.py cloud/jobs/week7_weather/weather_job.py src/dataforge/weather.py src/dataforge/dq tests/week9 scripts/week9_fault_inject.py`: **passed**.
- `python -m compileall -q src/dataforge/dq cloud/jobs/week7_weather/validation.py cloud/jobs/week7_weather/weather_job.py src/dataforge/weather.py tests/week9 scripts/week9_fault_inject.py`: **passed**.
- PyYAML parse of `quality/gx/weather_landing.yml`, `dbt/dataforge/models/week9_tests.yml`, and `tests/week9/faults/manifest.yml`: **passed**.
- Jinja syntax parse of both `dq_*.sql` macros: **passed** (not a dbt invocation).
- `dbt parse --no-partial-parse --project-dir D:\DATA_ENGINEER\DataForge_w9_q\dbt\dataforge --profiles-dir D:\DATA_ENGINEER\_tmp\w9_q_dbt_profile_20261118 --target offline` with pinned dbt-core 1.11.17 / dbt-bigquery 1.11.3: **passed** with the flag unset and with `DATAFORGE_DQ_RESULTS_ENABLED=true`; manifest `store_failures` values were bool `False` by default and bool `True` when enabled for F02, F10, and the four baseline PK tests. No warehouse connection was made. `dbt build` and live result-hook execution remain **UNVERIFIED**.
- The temporary profile at `D:\DATA_ENGINEER\_tmp\w9_q_dbt_profile_20261118\profiles.yml` is a copy of `profiles.example.yml` with the offline target (`dataforge-offline-project`) and no credentials. Automatic review rejected my cleanup command; I did not retry, so the temporary profile directory remains.
- Existing `pytest tests/mini3_api/test_weather_job.py -q` in the pinned W9 Python 3.12.13 environment: **11 passed**. An earlier system-Python attempt had 2 import errors for missing `google.cloud.bigquery`; no packages were installed, and the pinned-environment rerun supersedes that mismatch.
- CI run IDs and exact-head status: **UNVERIFIED** because GitHub access is blocked at `github.com:443`; integrator will batch remote operations.

## Integrator actions

1. Add the Dockerfile copy hunk above and enable `DATAFORGE_DQ_RESULTS_ENABLED` only in the W9 isolated job environment; do not build or deploy the W7 image from this lane.
2. Wire `dq_write_run_results(results)` in `dbt_project.yml` and ensure `store_failures` lands in the exact `dataforge_dq` dataset.
3. After G-PR1 merges, add the restricted/safe customer PK tests in Q-PR2, keeping their failure rows limited to authorized synthetic identifiers.
4. Reconcile the preexisting landing-range/key dbt tests with the G1 owner map and the F02 G2 defense.
5. After O provisions the authorized datasets and WIF identities, verify the G1 BigQuery source path and result writer, run dbt parse/build, execute F07/F10 on isolated fixtures, and record the exact-head CI run IDs.
