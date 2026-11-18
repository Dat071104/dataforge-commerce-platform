# W9-1 Controller report — S-A Soda Core

Status: COMPLETE. Source: D:\DATA_ENGINEER\_tmp\w9_spikes\soda\report.md. This summary is written by the integrator from the worker's temp-only report and independent verification.

## Scope and evidence

- Input: immutable Parquet slice SHA-256 ad79df00245dcdd0a909e08093fe70e02c07884e65dce445d2f3dc5f9114e798; 21 rows, 7 dates, exactly 3 rows/date.
- Worker reports no repository edits, GCP access, or Soda Cloud use.
- Integrator re-ran clean Soda verification (exit 0) and F06 volume mutation (exit 1; only the expected row-count check failed). Source Parquet remained unchanged.
- Evidence level: temporary local spike; no CI (Linux runner), live GCP, or observed-days claim.

## Results

| Criterion | Result |
|---|---|
| Version | soda-core 4.31.0; soda-duckdb 4.31.0; DuckDB 1.5.6; Python 3.12.13 |
| License | PyPI Proprietary; upstream Elastic License 2.0 |
| LOC | 60 nonblank contract-check lines; no standalone runner |
| Runtime | Worker measured one contract test plus verify at 4.646 s; integrator later measured five clean Soda CLI verifications at 2.7039 s median / 4.3044 s max |
| Peak RSS | Worker did not measure; integrator later sampled 100.7 MiB maximum across the Soda process tree at 20-ms intervals |
| Install footprint | 84.62 MiB site-packages |
| BigQuery connector | Official docs list soda-bigquery/ADC; not live-tested |
| Error detail | F06 message has check and threshold but omits date and observed count |

Post-G-A supplemental integrator measurement: five clean CLI verification runs all exited 0 with PYTHONIOENCODING=UTF-8; Windows process-tree RSS was sampled every 20 ms. These CLI wall times include process startup and are not directly comparable to GX in-process validation timings.

## Check mapping

| Spike check | Fault mapping | Result |
|---|---|---|
| Schema and physical types | F05a | Clean pass after DuckDB information_schema workaround; built-in schema check was NOT_EVALUATED |
| Three rows per date | F06 | Clean pass; isolated missing-province mutation failed only this check |
| Composite grain uniqueness | F02 | Clean pass |
| Physical ranges | F03 | Clean pass; precipitation -5 / temperature 99 mutation detected |
| Freshness at 36 hours | F07 | Clean pass; 48-hour stale mutation detected |
| Clean negative control | F-N0 | Clean scan had no failed checks; alert delivery was not part of this spike |

## Risks and integrator action

Soda v4.31.0 required a DuckDB-specific schema metric because its built-in schema check returned zero columns; the documented group_by type was rejected, and two metric checks needed distinct qualifiers. Root verification on Windows cp1252 emitted UnicodeEncodeError logging traces for emojis while retaining expected exit codes; Linux behavior is UNVERIFIED. License status is a material risk for the public MIT repository. Integrator selected GX D-2; Soda is not added to the repo.
