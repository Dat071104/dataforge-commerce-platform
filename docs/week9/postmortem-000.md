# Postmortem-000 — Oct30 calendar-window false positive

**Status:** Draft  
**Incident time:** 2026-11-17, during the S4 replay of observation date 2026-10-30  
**Evidence level:** W7 live-GCP failure and unchanged-Gold verification; PR #39 merge-SHA CI; local image preflight. The corrected image was not pushed or applied, so the live runtime fix is unverified.

## Summary

A blocking dbt calendar-window test failed while rebuilding the 2026-10-30 slice. The gate stopped the run before publication, which was the correct safety action. The test was wrong: it compared two mathematically equivalent FLOAT64 sums using exact equality and treated machine-rounding differences as a data-quality failure.

## Timeline

- **2026-11-17 23:29:40 +07:** W7 began a backfill DagRun for observation date 2026-10-30.
- **During the dbt build:** 48 of 49 tests passed. `assert_mart_weather_province_daily_calendar_windows` failed on two 2026-10-31 results. HCM returned actual `30.2` versus expected `30.199999999999996`; HN returned actual `10.2` versus expected `10.200000000000001`.
- **Before publish:** the Airflow run stopped at `wait_for_dbt_weather_build`; `publish_weather_gold` was not reached.
- **2026-11-17 23:43:24–23:44:12 +07:** Monitoring incident `0.of4kisi4m2aw` opened and closed. The email receipt was not confirmed by the user; this was an operational incident, not a deliberate drill.
- **2026-11-18:** PR #39 merged at `6b256f2eced7c2871d9c67f55633fd3e70ca3c34`. DataForge CI, Pages, and Week 7 CI all passed on the merge SHA.

## Impact

The run was blocked before publication. W7 evidence reports the published Gold snapshot stayed at 21 rows across 7 dates, with no duplicate grains; the Oct25–31 window checksum was unchanged. No bad rows were published. MTTD and MTTR were not calculated for this false-positive analysis.

## Root cause

The test used exact `IS DISTINCT FROM` equality for FLOAT64 rolling-window sums. Equivalent calculations can produce adjacent representable values because floating-point addition order affects the final bits. The discrepancies were approximately `3.55e-15` and `1.78e-15`; the model output was within expected precision. The failure was in the test comparison, not the weather data or the publication guard.

## Resolution and deployment status

PR #39 changed the FLOAT64 comparison to use absolute tolerance `1e-12` while preserving explicit NULL parity. Its merge-SHA checks passed. A local DataOps image candidate and offline dbt preflight were recorded later, and a live read-only comparison with the tolerance returned zero mismatches. The deployment preview showed only an image update, but the candidate image was not pushed to Artifact Registry and Terraform was not applied. Therefore the source correction is merged, while the live Cloud Run image correction is **unverified**.

## False-positive handling policy

- Keep the P1 gate blocking. Do not bypass it or alter data to fit the assertion.
- Classify a clean-data comparison failure as `DQ_FALSE_POSITIVE`; inspect the check and evidence, then correct the test logic and add the clean case to its fixture.
- Use the shared W9 float-equality macro with the documented tolerance and NULL parity. Include F-N0 so clean data must produce zero alerts.
- Treat any claim of production correction as unverified until the corresponding live image or exact runtime is confirmed.

## Evidence and limits

- W7 RCA: `D:\DATA_ENGINEER\DataForge_D_Week7_Final\evidence\s4-noop-oct30-rca-20261117.md`
- W7 PR #39 merge and merge-SHA checks: `evidence/pr39-merge-20261118.log`, `evidence/pr39-merge-sha-ci-6b256f2-terminal-20261118.json`
- W7 tolerance deployment preview: `evidence/c13-dbt-image-float-tolerance-plan-note-20261118.md`
- The later 2026-11-18 publication-run guard rejection is a separate incident and is not analyzed in this postmortem.
