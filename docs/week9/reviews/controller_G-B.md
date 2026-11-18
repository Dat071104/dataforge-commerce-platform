# Controller gate G-B — W9-2

**Verdict: REVISE**  
**Review date:** 2026-11-18  
**Review type:** one read-only controller gate; no cloud commands, no worker-file edits, no second G-B review.

## Scope and evidence boundary

Reviewed local W9 worktrees against base `ab345f7`: O `17fab2e` (includes the W9-B docs and I-1 follow-up), Q `247d9b5` (Q `fe6c7ae` plus integrator wiring), and G `fba7c4c`. The review artifact is written to the assigned integration worktree. The worker code is not yet present on one exact integrated head, and exact-head CI was not available.

No P0 code-execution, data-grain, customer-data leakage, or fabricated-evidence blocker was found in the tracked local material reviewed. A material WIF trust-boundary gap, incomplete cloud/CI acceptance, and stale audit statements keep this gate from GO. A new uncommitted O ledger update also records a Slack webhook secret version and says its source file remains outside the repository; I did not inspect or touch that file.

## Acceptance matrix

| Area | Result | Evidence and limit |
|---|---|---|
| O1 Terraform source | PASS, with a major security follow-up | `DataForge_w9_o/cloud/terraform/week9_dataops/wif.tf` checks numeric repository and owner IDs. The CI service account is scoped to named datasets and two secrets in the O worktree’s `datasets.tf` and `secrets.tf`. It does not constrain the GitHub ref, workflow, or event. |
| O1 cloud state | PASS by recorded cloud receipt; not re-queried here | O lane and `DataForge_w9_o/docs/week9/evidence/terraform-i1-wif-provider-rca-20261118.md` report 24/24 resources after the reviewed provider-only retry. No API was enabled and no BigQuery data rows were written. An uncommitted O ledger update records Slack secret version 1 as ENABLED; no HMAC-key version is recorded. The old 24/0/0 plans are stale and marked DO NOT APPLY. WIF positive/negative workflow tests remain UNVERIFIED. |
| O2/O3 local checks | PASS by lane receipts | Pre-commit config, Ruff, SQLFluff, YAML and Data Contract lint passed per `DataForge_w9_o/docs/process/lanes/w9-o.md`. Toolbox build/smoke, Gitleaks, and exact-head CI remain UNVERIFIED; the detect-secrets scan had 478 untriaged candidates and is not a clean secret-scan result. The O ledger says its user-provided webhook source file remains after a deletion attempt was rejected. |
| Q local behavior | PASS by lane receipts | `DataForge_w9_q/docs/process/lanes/w9-q.md` records 31 W9 tests, 11 existing weather-job tests, and offline dbt parse as passing. I did not rerun Q tests: the available Python 3.12 venv lacks both pytest and GX 1.25.0. The Q worktree’s `tests/week9/fault_matrix_report.md` records 13 PASS / 2 UNVERIFIED; F07 and F10 need isolated dbt/BigQuery execution. Local F-N0 is not live alert evidence. |
| G local behavior | PASS, independently checked | `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; $env:PYTHONPATH='src'; python -m pytest tests/week9/governance -q` — exit 0, 11 passed under system Python 3.13.9. `$env:PYTHONPATH='src'; python scripts/week9_classification_coverage.py` — exit 0, 351/351 total columns and 55/55 Gold columns. With `$env:PYTHONPATH='src'`, `python scripts/week9_pii_guard.py --manifest tests/week9/governance/fixtures/safe_masked_manifest.json` — exit 0; the same command using `f13_public_email_manifest.json` — expected exit 1 with one sanitized finding. |
| G Terraform/dbt/access | UNVERIFIED | G lane records no G4 impersonation, policy-tag plan/apply, API check, dbt parse/build, or live BigQuery test. The 4 policy-tag/data-policy groups and opt-in-off defaults are visible in `policy_tags.tf`; live enforcement and analyst denial are not proven. |
| Exact-head CI / publication | UNVERIFIED | O/Q/G report GitHub access blocked at `github.com:443`; no exact-head run IDs exist. This review does not authorize push, merge, deploy, API enablement, or data/secret writes. |

## Findings

### Major — restrict the WIF trust before any W9 OIDC job uses it (owner: O / integrator)

`DataForge_w9_o/cloud/terraform/week9_dataops/wif.tf:32` accepts a token when only `repository_id` and `repository_owner_id` match. The service-account principal bindings at lines 46 and 56 then grant that repository principal access to a CI identity with dataset write and secret-access grants. The O2 workflow (`DataForge_w9_o/.github/workflows/week9-dataops.yml`) has only `contents: read` and does not request `id-token: write`, so this is not evidence of an active W9 job or compromise. It is still too broad to authorize the planned WIF-backed CI: bind the provider to the approved ref/workflow or protected environment, and add negative tests for unapproved refs/workflows before use. The GitHub-side WIF tests are currently UNVERIFIED.

### Major — reconcile the cumulative cost/audit record (owner: O / integrator)

The integration copy [`cost_ledger.md`](../cost_ledger.md:3) says no resource write and no apply, while the O worktree copy `DataForge_w9_o/docs/week9/cost_ledger.md` has the I-1 apply rows but retains a stale first-paragraph “no W9 resource write” statement. The O ledger’s uncommitted update also records H-W9-1 Slack secret version 1 enabled at 23:09 +07, estimated at USD 0.01381 for 7 days (USD 0.01387 including the earlier query); the settled bill is unavailable. Synchronize the integration ledger and correct the O header before treating either as a current audit record. Keep the recorded limits explicit: W9 cap USD 3.00, stop USD 2.40; the current seven-day projection remains far below the W9 stop, but the maximum combined reserve is USD 15.99274 against a USD 16 stop, only USD 0.00726 of headroom. C10 state storage and the invoice remain unmeasured/unavailable. Refresh preflight before every paid action; integrator owns all plans/applies and API enables.

### Major — finish acceptance before advancing to release or a live run (owners: Q, G, O / integrator)

F07/F10, the GX BigQuery connector/result writer, G4 access, policy-tag feasibility, and exact-head CI/Gitleaks remain UNVERIFIED. Q’s matrix/lane still say the isolated dataset is not provisioned, but O1 has provisioned the empty `w9_drill` and `dataforge_dq` datasets; the reason those probes remain open is that no isolated test rows/table and live execution evidence exist. Update `DataForge_w9_q/docs/week9/fault_matrix_report.md` and `w9-q.md` to distinguish an empty provisioned dataset from an untested runtime. Also reconcile the pre-existing landing key/range tests that Q identified as overlapping G1 ownership before claiming the one-owner map is complete.

### Major — account for the Slack webhook source file (owner: root / integrator)

The uncommitted O ledger update says Secret Manager version 1 for `w9-slack-webhook-url` was created from a user-provided file at 23:09 +07, but the source file remains at `D:\DATA_ENGINEER\DataForge_D_Week7_Final\.w9_slack_webhook.txt`. It records that automatic policy review rejected `Remove-Item` and the deletion was not retried; no reason is recorded. The payload was not printed, and I did not read or touch the file. Treat the path as a live local credential source and have the user/root owner resolve secure cleanup; do not repeat the rejected deletion from this controller task. The version adds an estimated USD 0.01381 over 168 hours (or USD 0.17753 over 90 days if retained); it remains inside the recorded W9 cap, but retention and cleanup need an owner.

### Minor — fix committed-tree evidence drift (owners: G and integrator)

G’s coverage script returns **18** models, while the `G1-CLASSIFICATION-001` row in `DataForge_w9_g/docs/process/lanes/w9-g.md` says 17. Gold’s 55 columns are a subset of the 213 model columns, not an additional total. Clarify the count relationship. Also, `git diff --check ab345f7...HEAD` in the G worktree exits 1 for a new blank line at `dbt/dataforge/models/pii/marts/schema.yml:57` and trailing spaces in `docs/process/lanes/w9-g.md:3-4`; clean those before merge. The lane’s bare `git diff --check` receipt does not check the committed range.

## Authorization, cost, and next steps

- Keep W9 dataset contents synthetic-only. No BigQuery data row, API enable, or G4 access test is evidenced. Slack secret version 1 is now recorded; no HMAC-key version is recorded. G’s temporary operator `TokenCreator` bindings default off and must remain off outside the approved G4 window. AF13 remains NO in the prior G-A record; no real Vietnamese personal data is authorized by this gate.
- Do not reuse either stale O1 plan. O/integrator should tighten WIF trust, prepare a fresh reviewed plan for any change, and run positive/negative identity tests. Do not use WIF from an unverified workflow.
- Correct the cost-ledger and lane status drift. Preserve the 24/24 applied-state receipt and clearly separate control-plane state from data/secret writes.
- When GitHub access is available, run Gitleaks and exact-head CI; record run IDs. Before any further paid action, refresh Week 7/8/W9 usage, confirm the W9 stop line, and review the relevant Terraform plan.
- After separate integrator preflight, Q owns isolated F07/F10 and connector/result-writer checks; G owns the policy-tag plan and synthetic G4 allow/deny checks, including removing temporary impersonation grants afterward. No live query, plan/apply, or alert was run for this controller review.

**Readiness:** not ready for release, merge approval, or a W9 live-runtime phase. Address the WIF trust condition and record drift, then complete the scoped CI and isolated runtime checks under refreshed authorization/cost review. This is the single G-B verdict.
