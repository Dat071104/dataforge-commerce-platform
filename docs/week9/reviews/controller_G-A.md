# Controller verdict — G-A (W9-1)

**Overall: GO**

**Reviewed:** 2026-11-18 · **Scope:** W9-0 foundations and W9-1 tool decision gate · **Evidence boundary:** local/offline and exact-head CI as stated below.

## Summary

W9-A is merged at `ab345f7`; its exact-head PR checks passed on `49dd13c`. The three ODCS contracts lint against v3.2.0, the failure catalog keeps F01–F15 / F-T1 / F-N0 unchanged, the RFC is a Draft with proposed SLOs, the baseline is reproducible from a dbt manifest, and the landing schema refactor compiles offline for both schema values. The paired local spikes selected Great Expectations Core 1.25.0 for G1. No P0 blocker prevents starting W9-2.

## Acceptance matrix

| Area | Result | Evidence / limit |
|---|---|---|
| W9 authorization / scope | PASS | Addendum F signed; AF13 remains NO. No W9 resource configuration or source-table write occurred; only an AF3-authorized read-only BigQuery query job ran. The read-only slice query used the approved weather source and did not write to BigQuery or GCS. |
| W9-A merge and CI | PASS | PR #41 merged normally at `ab345f7`. Exact-head DataForge CI `44302990650`, Week 7 CI `44302990427`, Pages `44302990318` succeeded on `49dd13c`. Post-merge runs `44305441759`, `44305442091`, and `44305441845` succeeded on `ab345f7`. |
| Required check policy | PASS | Active `main-release-guard` requires `pipeline` from GitHub Actions; exact-head `pipeline` check succeeded. The keyless dbt compile job was skipped, but it is not a required check and no live WIF identity exists yet. |
| Baseline | PASS | `scripts/week9_baseline.py` on the `6b256f2` manifest: 14/16 models with a uniqueness/grain check; 14/16 model descriptions; 12/22 Gold column descriptions; 7/7 sources with freshness; 0 catalog-mapped W9 fault fixtures. The baseline explicitly says uniqueness coverage is not a complete nullability/PK pair. |
| Failure catalog | PASS | `docs/week9/failure_modes.md` preserves F01–F15, F-T1, F-N0 and defines detector IDs, severity and expected action. It is labeled planned; no fault fixture or gate is claimed implemented. |
| Data contracts | PASS | `datacontract lint` passed for all three ODCS v3.2.0 contracts with CLI 1.2.8. Each rule’s ODCS-safe `quality.id` maps to the unchanged dotted `check_id` in its description. Structural lint does not test actual data. |
| Drill isolation | PASS | Local `dbt parse --no-partial-parse` and `dbt compile --no-introspect --target offline` passed with `DBT_WEATHER_LANDING_SCHEMA=weather_mini3` and `w9_drill`; manifest source schema was inspected for both. No BigQuery job was run by dbt. |
| RFC | PASS | RFC-001 is Draft with the required headings, proposed SLI/SLOs, error budget, design, alternatives, privacy, cost and rollback. SLOs are not 30-day observed. Mentor review is pending. |
| D-2 tooling | PASS | The criteria were written before paired spikes. GX 1.25.0 was selected; Soda v4.31.0 was not selected. Check details and trade-offs are in the ADR and spike reports. |
| BigQuery connector | UNVERIFIED | Official docs document GX BigQuery support and its `bigquery` extra; no live connector test was run. Upstream GX changelog says some BigQuery backend tests are temporarily skipped. This must be verified on the W9 isolated dataset before claiming live-GCP support. |
| Spike cleanliness | PASS | Both workers used the same immutable 21-row slice, made no repo/GCP edits, and left its SHA unchanged. Integrator reran GX’s full spike script (exit 0) and Soda clean/F06 cases (exit 0 / expected exit 1). |
| Tooling/CI evidence | PASS with limits | W9-A exact-head CI is Linux-runner evidence. Soda/GX comparisons are temporary local spikes, not CI or live-GCP evidence. Gitleaks is not installed locally; the integrator’s high-confidence token/private-key pattern scan found zero matches. |
| Cost | PASS | Week 7 estimate ≈USD 12.89274; W8 reserve ≤USD 0.10; W9 cap USD 3.00: combined cap reserve USD 15.99274, below the USD 16 stop line by USD 0.00726. The slice query billed 10 MiB minimum; gross list-price estimate ≈USD 0.00006. Invoice unavailable. |

## Findings

### Critical

None.

### Major follow-up — owned by Worker Q / integrator in W9-2

1. The GX BigQuery connector is documented but unverified live. Worker Q must test the pinned GX BigQuery extra against `w9_drill` or a PR dataset through the authorized WIF identity, set `maximum_bytes_billed=1 GiB`, and record the result. Do not connect the spike to production or use Soda Cloud.
2. The G1 physical bounds (precipitation ≥ 0 mm and temperature −90…70 °C) and freshness thresholds must be exercised against a clean isolated fixture before `DQ_ENFORCE=block`. F-N0 must still produce zero P1/P2 rows and zero alerts.
3. The GX runner must wrap raw messages with `check_id`, date, severity, threshold, action and sanitized counts; the spike showed schema/row-count/freshness messages alone are not sufficiently actionable.

### Minor

- Soda v4.31.0 has Proprietary PyPI metadata / Elastic License 2.0, plus DuckDB schema and `group_by` gotchas; it was not selected. Soda v3.5.6 is a legacy, unmeasured alternative.
- The Windows Soda CLI emitted UnicodeEncodeError logging traces under CP1252 even though expected exit codes were preserved. This is a local-console limitation; the chosen engine is GX and the Linux CI behavior remains to be measured.
- No gitleaks executable is installed locally. The W9-2 DataOps lane must enforce the planned CI secret scan before future pushes.

## Exact checks inspected or executed

- `datacontract lint contracts/weather_landing.v1.yaml` — exit 0.
- `datacontract lint contracts/mart_weather_province_daily.v1.yaml` — exit 0.
- `datacontract lint contracts/open_meteo_api.assumptions.yaml` — exit 0.
- `python scripts/week9_baseline.py` — exit 0; metrics listed above.
- `dbt parse --no-partial-parse --target offline --profiles-dir .` and `dbt compile --no-introspect --target offline --profiles-dir .` under both landing-schema values — exit 0.
- `ruff check scripts/week9_baseline.py` and `python -m pip check` in the Python 3.12.13 dev environment — exit 0.
- Soda temp command `soda contract verify --data-source ds_config.yml --contract contract.yml` — exit 0; F06 mutant command — expected exit 1.
- GX temp command `.venv/Scripts/python.exe gx_spike.py` — integrator rerun exit 0; source Parquet SHA unchanged.
- BigQuery read-only job `w9_spike_slice_20261118_01` — DONE; 8,008 bytes processed / 10,485,760 bytes billed; local Parquet 21 rows, 7 dates, duplicate key count 0. No destination write.

Two initial contract lint failures were fixed before W9-A merge: dotted values were invalid as ODCS `quality.id`, and a team member object lacked required `username`. The final contracts pass. The first multiline BigQuery dry-run failed with `Unrecognized name: province_id`; a single-line dry-run validated at 2,632 bytes, then the bounded query succeeded. The failed dry-run created no query job.

## Resolved preflight failures and exact commands

- datacontract lint contracts/weather_landing.v1.yaml first exited 1 because quality.id values containing dots did not match the ODCS v3.2.0 identifier pattern. After converting ODCS ids to safe slugs and keeping the unchanged dotted check_id in each description, lint found the next issue: data.team.members[0] lacked the required username. The final contract uses team-level ownership without fabricating a person. RCA: D:\DATA_ENGINEER\DataForge_D_Week7_Final\evidence\w9\contract-lint-rca-20261118.log.
- First BigQuery dry-run command bq query --dry_run --use_legacy_sql=false --project_id=dataforge-p7-lab-d0f725 --location=us-central1 --maximum_bytes_billed=1073741824 <multiline SELECT...> exited 1 with Unrecognized name: province_id at [1:8]. Best-supported cause was the multiline query argument passed through Windows bq.cmd/cmd.exe. The single-line dry-run then validated at 2,632 bytes; the actual capped read-only query completed. RCA: D:\DATA_ENGINEER\DataForge_D_Week7_Final\evidence\w9\bq-dry-run-rca-20261118.log.
- bq show -j --project_id=dataforge-p7-lab-d0f725 --format=prettyjson w9_spike_slice_20261118_01 did not produce JSON for the local PowerShell pipeline; ConvertFrom-Json reported Unexpected character encountered while parsing value: B. Job metadata was retrieved read-only through BigQuery Jobs REST instead; the query job was DONE with the expected bytes. This was a controller-environment/tool invocation issue, not a job failure.

## Cloud/publish authorization and readiness

AF0–AF10 are authorized only within their exact scopes and caps; AF13 remains NO. Current project is `dataforge-p7-lab-d0f725` / `955038620072`. No W9 datasets, identities, APIs, alerts, or secrets were created; `datalineage.googleapis.com` remains disabled. The cost ledger records the AF3 read-only BigQuery job estimate; the settled invoice is unavailable.

**Readiness: GO to W9-2.** Workers O, Q, and G may start on their assigned files. Worker Q should use GX Core 1.25.0 for G1; the integrator reviews every plan, performs every apply/API enable, and owns the W9 cost stop line. G-A is complete; do not call the controller again for this gate.
