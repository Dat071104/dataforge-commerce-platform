# W9 foundation verification

Captured 2026-11-18. This record separates local/offline evidence from CI, live-GCP, observed-days and mentor-approved evidence. No W9 CI or live-GCP result is claimed here.

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

## Not yet evidenced

- Exact-head Linux CI for W9-A: not run; PR is not yet open.
- Live GCP isolated-dataset build, WIF, access tests, alert receipt, or lineage: not run; no W9 GCP writes have occurred.
- No gitleaks executable is installed locally. A high-confidence staged-diff scan for private keys, GitHub/Slack/Google/AWS tokens, and credential URLs passed with zero matches; this is a manual pattern scan, not gitleaks or CI evidence.
- Full fault matrix and F-N0: not implemented.
- Mentor review: pending; RFC status is Draft.
