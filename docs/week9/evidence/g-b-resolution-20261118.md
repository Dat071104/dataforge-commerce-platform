# G-B REVISE resolution log — 2026-11-18

This is the integrator's follow-up to the one-time read-only review in [`controller_G-B.md`](../reviews/controller_G-B.md). The controller verdict remains **REVISE**; no second G-B review was requested or run.

| Finding | Integrator action | State |
|---|---|---|
| WIF provider trusted any workflow in the authorized repository | Kept the numeric repository/owner ID checks and added `workflow_ref` + event mappings. The applied condition allows only `week9-dataops.yml`, `week9-cleanup.yml`, `week9-cd.yml`, and `week9-catalog.yml` for `pull_request`, `push`, `workflow_dispatch`, and `schedule`. Provider update plan: 0 add / 1 change / 0 destroy; a read-only GCP description confirmed the condition. | Provider trust is narrowed. GitHub-side WIF positive/negative tests and a negative test for an unapproved workflow are still **UNVERIFIED** pending remote CI. |
| Cost ledger and cloud state were stale | Synced the O1 state, provider-only retry, Slack secret version, and current estimates into `cost_ledger.md` and `foundation_checks.md`. Current seven-day W9 gross estimate is ≈USD 0.01387 (read-only query + one Slack secret version) plus unmeasured C10 state storage; W7 estimate ≈USD 12.89274; W8 reserve up to USD 0.10; combined current projection ≈USD 13.00661. The combined maximum reserve remains USD 15.99274 against the USD 16 stop. | Ledger is current to these actions; invoice unavailable. The W9 source webhook file remains locally because automatic policy review rejected its deletion; the URL was never printed. Manual file cleanup is pending. |
| Q reports implied that the isolated datasets did not exist | Updated Q lane/fault-matrix documentation: O1 provisioned empty `w9_drill` and `dataforge_dq` datasets, but no `weather_landing` table/data or live dbt/BigQuery execution exists. | F07 and F10 remain **UNVERIFIED** for the correct reason; local matrix remains 13 PASS / 2 UNVERIFIED. |
| G classification counts and diff evidence were stale | G lane cleanup reports 18 models / 213 model columns, 351 total classified columns, and 55 Gold columns as a subset of that total. The G branch cleanup commit ran `git diff --check ab345f7..HEAD` successfully. | **Resolved locally** in G commit `b13b6a1`; CI remains **UNVERIFIED**. |

## Remaining gate evidence

- Exact-head GitHub CI and Gitleaks are still **UNVERIFIED** because `github.com:443` is blocked on the current network. The user was asked once to switch to 5G; no remote retry was attempted.
- WIF's GCP condition is applied, but the positive WIF run, denied production-dataset operations, and unapproved-workflow negative test still need exact-head workflow evidence.
- G4 policy-tag plan, synthetic load, and analyst/privileged allow/deny checks have not run. G1 BigQuery connector/result-writer, F07/F10, alerts, and lineage remain unverified.
- No real Vietnamese personal data was used. No BigQuery data rows or HMAC secret version were created, and no data-policy or lineage API was enabled in this follow-up.
