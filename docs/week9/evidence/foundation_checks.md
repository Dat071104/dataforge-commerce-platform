# W9 foundation verification

Captured 2026-11-18. This record separates local/offline evidence from CI, live-GCP, observed-days and mentor-approved evidence. One read-only live-GCP source query is recorded below; no W9 GCP write or isolated-dataset result is claimed.

## Local offline evidence

| Check | Result | Evidence level |
|---|---|---|
| dbt versions from pinned Week 7 lock | dbt-core 1.11.17; dbt-bigquery 1.11.3 | implemented / version inventory |
| `dbt parse --no-partial-parse --target offline` with `DBT_WEATHER_LANDING_SCHEMA=weather_mini3` | Exit 0 | local offline parse |
| `dbt compile --no-introspect --target offline` with `DBT_WEATHER_LANDING_SCHEMA=weather_mini3` | Exit 0; 16 models found | local offline compile; no BigQuery job |
| `dbt parse --no-partial-parse --target offline` with `DBT_WEATHER_LANDING_SCHEMA=w9_drill` | Exit 0; manifest source schema resolved to `w9_drill` | local offline parse |
| `dbt compile --no-introspect --target offline` with `DBT_WEATHER_LANDING_SCHEMA=w9_drill` | Exit 0; 16 models found | local offline compile; no BigQuery job |
| `datacontract lint` on all three ODCS contracts | Exit 0 for each with datacontract-cli 1.2.8 / ODCS v3.2.0 | local contract lint |
| `python scripts/week9_baseline.py` | 14/16 PK/grain uniqueness checks; 14/16 documented models; 12/22 documented Gold columns; 7/7 sources with freshness; 0 mapped W9 fault fixtures | local manifest analysis |
| Ruff on `scripts/week9_baseline.py` | Exit 0 | local lint |
| `pip check` in Python 3.12.13 dev environment | Exit 0, no broken requirements | local dependency check |

The dbt offline profile points to the non-existent project `dataforge-offline-project`; compile did not connect to BigQuery or execute a query. The manifest check confirmed both landing schema values. The W9 baseline is from origin/main SHA `6b256f2`, before the W9 source refactor.

## Live GCP read-only source slice

- Table: dataforge-p7-lab-d0f725.weather_mini3.weather_landing in us-central1. Metadata read showed 60 rows, 22,880 bytes, daily partitioning by observation_date, and the expected 11 columns.
- A dry-run of the October 25–31, 2026 query validated with a 2,632-byte estimate. The single read-only query job w9_spike_slice_20261118_01 completed; 8,008 bytes were processed and 10,485,760 bytes billed for the minimum charge, under maximum_bytes_billed=1 GiB.
- Local slice: D:\DATA_ENGINEER\_tmp\w9_spikes\data\weather_7date_slice.parquet; 21 rows, 3 rows per date across seven dates, zero duplicate request/province/date keys; SHA-256 ad79df00245dcdd0a909e08093fe70e02c07884e65dce445d2f3dc5f9114e798.
- Gross on-demand list-price estimate: about USD 0.00006 before any account free tier; invoice unavailable. No BigQuery or GCS destination write occurred. Evidence level: live GCP (read-only prod source), not live GCP isolated dataset.
## Not yet evidenced

- W9-A exact-head CI (Linux runner): DataForge CI run 44302990650, Week 7 CI run 44302990427, and Pages run 44302990318 succeeded at head 49dd13c. The keyless dbt compile job was skipped and is not a required check. Post-merge runs on ab345f7 also succeeded: DataForge CI 44305441759, Week 7 CI 44305442091, and Pages 44305441845.
- Live GCP isolated-dataset build, WIF, access tests, alert receipt, or lineage: not run. One read-only copy from the prod weather source is recorded below; no W9 GCP write has occurred.
- No gitleaks executable is installed locally. A high-confidence staged-diff scan for private keys, GitHub/Slack/Google/AWS tokens, and credential URLs passed with zero matches; this is a manual pattern scan, not gitleaks or CI evidence.
- Full fault matrix and F-N0: not implemented.
- Mentor review: pending; RFC status is Draft.
