# W9-1 Controller report — S-B Great Expectations Core

Status: COMPLETE. Source: D:\DATA_ENGINEER\_tmp\w9_spikes\gx\report.md. This summary is written by the integrator from the worker's temp-only report and independent verification.

## Scope and evidence

- Input: immutable Parquet slice SHA-256 ad79df00245dcdd0a909e08093fe70e02c07884e65dce445d2f3dc5f9114e798; 21 rows, 7 dates, exactly 3 rows/date.
- Worker reports no repository edits or GCP access. The source Parquet hash matched before and after the spike.
- Integrator re-ran gx_spike.py in the worker's isolated venv; exit 0 verifies the clean case and all five isolated mutations.
- Evidence level: temporary local spike; no CI (Linux runner), live GCP, or observed-days claim.

## Results

| Criterion | Result |
|---|---|
| Version | Great Expectations Core 1.25.0 |
| License | Apache-2.0 |
| LOC | 263 nonblank, noncomment Python lines |
| Runtime | 0.2857 s median / 0.3367 s maximum over five clean runs |
| Peak RSS | 215.6 MiB during checks; 214.4 MiB baseline |
| Install footprint | 406,066,902 bytes (406.3 MiB) site-packages |
| BigQuery connector | Official compatibility, connection, and install docs; not live-tested |
| Error detail | Duplicate/range include counts; schema/row-count/freshness need a wrapper for actionable details |

## Check mapping

| Spike check | Fault mapping | Result |
|---|---|---|
| Schema and types | F05a | Clean pass; isolated missing-column mutation detected |
| Three rows per date | F06 | Clean pass; isolated 2/3-province mutation detected |
| Composite grain uniqueness | F02 | Clean pass; duplicate-key mutation detected |
| Physical ranges | F03 | Clean pass; precipitation -5 / temperature 99 mutation detected |
| Freshness at 36 hours | F07 | Clean pass; 48-hour stale mutation detected |
| Clean negative control | F-N0 | Clean case passed all checks; alert delivery was not part of this spike |

## Risks and integrator action

GX is selected for D-2 based on Apache-2.0 licensing, clean 5/5 validation, fast measured runtime, and manageable peak RSS. The package footprint is larger than Soda. BigQuery support is documented only; GCP isolated-dataset validation remains required in W9-2. Integrator must wrap GX errors with check_id, date, severity, threshold, action, and sanitized observed/failing counts.
