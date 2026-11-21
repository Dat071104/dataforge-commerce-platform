# Controller gate G-C — W9 final state before `v0.9.0-week9`

**Verdict: GO with follow-ups**  
**Review date:** 2026-11-21  
**Review type:** one read-only controller gate. No GCP command, no push/commit/merge, no repo-variable change, no worker-file edit. This file is the only write.

## Scope and evidence boundary

Reviewed repo `Dat071104/dataforge-commerce-platform`, worktree `DataForge_w9_g`, branch `feat/w9-z2-closeout` at head `13f5a38` (PR #58, OPEN, MERGEABLE) on main `0cf5a2e` (PR #57 merge). Primary sources were `gh run view --json conclusion,jobs` and `--log` for every cited run, small run artifacts (`gh run download` to a scratch folder), `gh pr view`, `gh variable list`, `gh api` job GETs, file contents, and `git diff 0cf5a2e..13f5a38`. I did not re-query GCP. Cloud-state claims (AF12 changes, final inventory, Terraform "No changes", G4 receipt, email receipt) are recorded operator claims. Where `gh` could corroborate them, I checked them. Otherwise they are marked UNVERIFIED. I did not open `.w9_slack_webhook.txt` or any credential file.

I found no fabricated or contradicted evidence, no secret or real personal data in tracked W9 files, and no cloud change outside the authorization rows. No status is claimed MET without a run or file behind it. The follow-ups below are wording drift, stale numbers, and a Terraform variable hazard for W10. None of them blocks the tag.

## Acceptance matrix

| Area | Result | Evidence and limit |
|---|---|---|
| W9-01 MET | PASS | `44867546904` (`pull_request_target`, #52 head `0f6c5fb`, success): all 16 local fault-fixture jobs succeeded, including F05b, F-T1 and F-N0. `44872770442` and `44873779562`: job "Isolated BigQuery faults F07 and F10" succeeded; log `LIVE_FAULT_RESULTS={"F07": "PASS", "F10": "PASS"}`. Artifact `fault_matrix_report.md` matches `fault_matrix.md:31-32`: injected/detected times, actions, 660,602,880 B, upper bound 1,734,344,704. F14: job `136744399247` failed at "Check contract compatibility against main" with `Removed property temp_max_c`. **Limit:** both F07/F10 runs ended `failure` at run level, because the 5-GiB run guard failed closed (`workflow_run_id="0"` in the fault-matrix artifact). This is disclosed (`fault_matrix.md:36`, RFC R-19). |
| W9-02 MET | PASS, partly UNVERIFIED | Operator drill log `h-w9-3-f06-drill-20261121.log` matches the evidence timeline: gate 26.4 s, Cloud Logging event 57.7 s, Slack ≤ 98.4 s, `delivery_failures: 0`. The alert policies are recorded in the inventory, not re-queried. Email receipt is user-confirmed and untimed (H-W9-3). The MTTR wording is inconsistent (Minor 3). |
| W9-03 MET | PASS | `44864861534` (success): OpenMetadata server/ingestion 2.0.7, `Processed records: 11`, `Errors: 0`, `Workflow Success %: 100.0`. Lineage: 5 weather links in `g7-lineage-w9-drill.md:13-19`. `g7-pii-lineage-20261121.json` has 2 links. The API-disable time (11:54:50) is an operator record. |
| W9-04 PARTIAL | PASS (status correctly not MET) | `44866987378` (`workflow_dispatch`, success): `W9_PII_PROOF=PASS rows=5 dbt_jobs=2 ci_mask=DENIED_BY_POLICY_TAG bytes_billed=10485760`; artifact `raw_policy_tagged_values_visible=false`. F13: job `136748255564` failed at `assert 56 == 55` (registry test), before the guard step. This matches the disclosed "CI blocked one step earlier". G4 is a local operator receipt (UNVERIFIED here). The legal mapping is labelled and the breach deadline stays `LEGAL_UNVERIFIED`. |
| W9-05 MET | PASS with wording follow-up | Keyless dbt build: job "Isolated BigQuery PR build and G1 gate" succeeded in `44873779562` (`dbt_ci_pr_57` created) and in `44882607355`. Cleanup `44883752761`: `CLEANUP=deleted dbt_ci_pr_56`. The cited run `44873779562` itself ended `failure` (R-19), and cloud checks were paused on several PRs and paused again at close-out (Minor 1). |
| W9-06 MET | PASS | `44882607355` (#56 head `f9ffba3`, success; workflow ref main `0cf5a2e`): `Data diff: prod=6, ci=6, prod_only=6, ci_only=6`, notice "Data diff found rows that require PR review", `W9_RUN_COST_GUARD=PASS paid_jobs=2 bytes_billed=828375040 guarded_upper_bound=1902116864`. CD `44882474347` (push main `0cf5a2e`, success) ran `--target prod_state` and uploaded `dataforge-prod-manifest`. Game-day timings in postmortem-001 are arithmetically consistent: MTTD 2:18, ack 33 s, MTTR 6:56. The sealed record is off-repo (UNVERIFIED). The diff is a non-blocking notice (RFC A3). |
| W9-07 MENTOR_CONFIRMATION_PENDING | PASS | RFC-001 is v0.3 "In review". The decision log answers a persona pre-review. H-W9-2 is not claimed held. |
| Run-level conclusions | Verified | Success: `44866987378`, `44867546904`, `44864861534`, `44882607355`, `44883752761`, `44882474347`, `44882474025`. Failure, all from the run guard (R-19, pull_request_target executes base-branch `4b2cef1` workflow code): `44872770442`, `44873779562`, `44882469242`. |
| R-22 race | PASS (verified) | `44882469242` was created 07:55:35Z (`ready_for_review`). #57 merged 07:55:37Z. Cleanup `44882474025` logged `CLEANUP=deleted dbt_ci_pr_57` at 07:55:57Z. The build logged `Dataset 'dataforge-p7-lab-d0f725:dbt_ci_pr_57' successfully created.` at 07:58:22Z. This matches `af12-closeout-20261121.md:16`. |
| Cost ledger final block | PASS (arithmetic) | Every byte figure was checked against the run-cost artifacts: 754,974,720 = 41,943,040 + 713,031,680 for `44875222761`, `44881425185` and `44882469242`; 828,375,040 = 115,343,360 + 713,031,680. Block sum, counting the first row as its +52,428,800 delta: 2,495,610,880 B = 2.324 GiB, which is USD 0.014186 at $6.25/TiB. The 14:30 block is 2,411,724,800 B, USD 0.013709. Known gross 0.01775 + 0.0137 + 0.0142 = USD 0.0457. Forecast 0.0457 + 0.01381 + 0.01794 + 0.11 = USD 0.18745 (≈ 0.19). Cumulative 12.89274 + 0.10 + 0.18745 = USD 13.18 < 16. Invoice/SKU/C10 remain UNVERIFIED (`cost_ledger.md:163`). |
| Terraform #58 | PASS, with a Major follow-up | `datasets.tf`: `w9_drill` and `ci_write_w9_drill` have `count = var.week9_drill_enabled ? 1 : 0`, two `moved` blocks to `[0]`, and `delete_contents_on_destroy = true`. `variables.tf:76-80`: default `false`. The diff is consistent with the recorded 0/1/0 + 2 moved at 15:08 (applied with `week9_drill_enabled=true`), the 0/0/4 at 15:15 (`w9_drill`, writer binding, two TokenCreator members; the userinfo data source is not a resource), and the later "No changes". "No changes" itself is UNVERIFIED (no GCP). The close-out variable set is not recorded (Major 1). |
| Authorization conformance | PASS | See the judgement-calls section. Nothing found outside AF2-ext-1/2/2b/2c, AF4, AF8, AF10, AF12. `gh` corroborates `W9_WIF_PR_TARGET_ENABLED=false` (updated 08:14:28Z = 15:14 +07) and #56 CLOSED at 08:12:04Z, unmerged. |
| Secret/PII hygiene | PASS | Tracked `docs/week9`, `docs/process/lanes`, `docs/SYLLABUS_COVERAGE.md`, `cloud/terraform/week9_dataops`, `governance`, `tests/week9` have zero hits for `hooks.slack.com/services`, `ghp_`, `github_pat_`, `AIza…`, `PRIVATE KEY`, `"private_key"`, `@gmail.com`, `xox?-`. Repo-wide, the only Slack-URL hit is the prefix validator `src/dataforge/dq/notifications.py:175`. There are no non-`example.com` personal e-mails in `docs/week9` and no Vietnamese mobile numbers. The 12-digit hits are the project number, job/run IDs, and test value `123123456789`. |
| Offline tests | NOT RUN locally; exact-head CI PASS | `D:\DATA_ENGINEER\_tmp\w9_drill_venv\Scripts\python.exe -m pytest …` exited 1 with `No module named pytest`. System Python 3.14.4 and the worktree `.venv` (3.13.9) also lack pytest/GX. Nothing was installed. Exact-head substitute `44884452763` (`pull_request`, `13f5a38`, success): `112 passed in 9.28s`, `PII_GUARD_STATUS=PASS findings=0 models_scanned=18`. |
| PR #58 exact-head checks | PASS so far | `pipeline` SUCCESS (`44884452780`, `44884437197`). W9 DataOps `pull_request` and `pull_request_target` runs succeeded with cloud jobs skipped (paused). Week 8 CDC "Compose integration (T1-T7)" was still IN_PROGRESS at review time. |
| Open items not claimed done | PASS | H-W9-2 pending. Breach deadline `LEGAL_UNVERIFIED` (`privacy_compliance.md:13,26`; RFC §7). RFC A1–A8 listed without a done status (`RFC:100`). Invoice UNVERIFIED (`cost_ledger.md:163`). |

## Findings

### Blocker

None.

### Major — record the Terraform close-out variable set before any W10 plan (owner: O / integrator)

`af12-closeout-20261121.md:13` and `w9-final-inventory-20261121.log:31` say the final plan "with close-out variables" returned `No changes`, but the values are not tracked anywhere. Several variables that keep AF4/AF6 resources default to `false`: `week9_pii_enabled` (`policy_tags.tf:13-17`), the impersonation and CI-writer flags, and `enable_dq_alerting` (`variables.tf:22-25`). A plain `terraform plan`/`apply` in W10 would therefore propose destroying the kept taxonomy, data policies, test SAs, log metrics and the three P1 policies. Before the next Terraform action, commit a non-secret close-out var file or runbook block listing every variable value used for the 15:16 plan, together with the plan's resource count. The reproducibility gap does not affect the tag.

### Minor

1. **W9-05 cites a failed run** (owner: integrator). `docs/SYLLABUS_COVERAGE.md:131` cites `44873779562` as the dbt-build example, but that run's conclusion is `failure` (R-19 run guard), and the row does not say so. "On every PR" also overstates the case: cloud checks were paused on #53/#54/#55 runs and are paused since 15:14. Cite `44882607355` (success), or annotate the failure, and add "cloud checks paused since AF12".
2. **Stale cost figures outside the final block** (owner: integrator). The `cost_ledger.md:9-10` "Approved limits / Current state" rows still show forecast ≈ USD 0.35950 (11:45) and "API enabled (LINEAGE_DAY 3/5) … hard off by 12:00". RFC `RFC-001…md:67` §9 still says forecast ≈ USD 0.37 and cumulative ≈ USD 13.36. The final ledger says ≈ USD 0.19 and 13.18. Sync both.
3. **H-W9-3 MTTR definition does not match its own timeline** (owner: integrator). `h-w9-3-f06-live-drill.md:27` defines MTTR as "data restored and gate green: 1 min 58 s". In the timeline (`:22-23`), only the restore happened at 14:02:46.213 (117.4 s ≈ 1 min 57 s). The gate re-run PASS was at 14:04:37.806 (3 min 49 s). Postmortem-001 measures MTTR to "verified green and resolved". Relabel 1 min 58 s as "time to restore" and use 3 min 49 s as the comparable MTTR, or state the definition. The same applies to `SYLLABUS_COVERAGE.md:132` ("MTTR 1 min 58 s").
4. **F-N0 live precision evidence is thin** (owner: Q). `w9-3-4-fn0-precision-20261121.log:3` shows `monitor` output without `routes`, which matches a run without `--send-alerts`. The gate JSON is truncated after the second check. "12 PASS events, 0 alerts" (RFC:45; drill doc :9) is therefore only partly shown. `events: 12` is shown; the per-event PASS status and the Slack routing decision are not. Keep the claim as the Monitoring-email negative control, or attach the untruncated output.
5. **Wrong pointer for R-1…R-15** (owner: integrator). `RFC-001…md:96` says R-1…R-15 are in `failure_modes.md`, which contains no R-IDs. Only R-2/3/7 (`cost_ledger.md:67-69`) and R-12/13/14 (`g3-g4-pii-proof-20261121.md:18`) appear in tracked docs. Fix the pointer.

### Note

- **Action-ID collision.** `postmortem-001.md:52-58` uses A1–A4, with A4 "Done", for items unrelated to RFC Appendix B A1–A8. Prefix them (for example GD1-A1) so that "A4 Done" is not read as RFC A4 (non-empty Gold hash), which remains open.
- **Ambiguous first row in the final cost block.** `cost_ledger.md:156` prints 754,974,720 in the Bytes column, but the total counts only the +52,428,800 delta. Adding the column as printed gives 2.98 GiB instead of 2.32 GiB. State the delta in the column.
- **"Addressed" is generous.** `postmortem-001.md:50` says gaps 5, 8 and 9 are addressed. The runbook (`drill-restore-and-closeout.md:32-35`) records them as known limits or an escalation path, not fixes. The runbook also does not say that `w9_drill` was destroyed at AF12; its procedure needs the re-enable path first (`af12-closeout-20261121.md:24-25`).
- **BOM in operator logs.** `h-w9-3-f06-drill-20261121.log` and `w9-3-4-fn0-precision-20261121.log` start with a UTF-8 BOM (EF BB BF), and the inventory log does not. This is cosmetic.
- **Data diff does not block yet.** The F15 data diff is a `::notice`, not a failing check. W9-06 MET rests on detection, and enforcement is RFC A3.
- **Legal citations not re-checked.** `privacy_compliance.md:9-13` cites Law 91/2025/QH15 Art. 20/39, Decree 356/2025 Art. 42(2), and Decrees 330/2026 and 363/2026. They are labelled "not legal advice", and the controller did not re-check them against official texts. Decree 13/2023 is correctly described as no longer generally in force. The breach deadline remains `LEGAL_UNVERIFIED`.
- **Postmortem-000 is still a Draft.** `postmortem-000.md:3` is a W7-incident postmortem and does not block W9.
- **Secrets outlive the W9 reserve.** Both secrets are kept for W10–W12. Their cost beyond the 7-day W9 reserve (Slack 90-day ≈ USD 0.17753 per `cost_ledger.md:33`) belongs in the W10 ledger.

## Authorization conformance and judgement calls

- **AF2-ext-1/2/2b.** The removal plan was 0/0/8, applied at 11:43 +07, before the 2026-11-23 deadline. The inventory shows CI-writer IAM 0 and ACL 0 on `restricted_pii`/`pii_safe`, and both custom roles deleted. This is a recorded claim and was not re-queried.
- **AF2-ext-2c.** The 6/1/0 plan was the authorized shape. The kept provider condition (`inventory:27`) carries the `pull_request_target` event list.
- **AF4.** The operator TokenCreator grants stayed from G4 until the 15:15 destroy. AF4 allows them until W9 close, so this conforms. The inventory records 0 grants on both test SAs.
- **AF8.** Lineage was disabled at 11:54:50, before the 18:00 hard-off (AF2-ext-2c) and on day 3/5. The lineage estimate is USD 0.01794, against a USD 0.80 stop. `dataplex.googleapis.com` was already enabled before W9 (`docs/cloud/evidence/live_foundation_inventory.json:51`), so AF1 "already-enabled stay" applies.
- **AF10.** No VM, firewall rule or NAT was created; OpenMetadata ran ephemerally in CI.
- **AF12.** `w9_drill`, every `dbt_ci_pr_*`, the TokenCreator grants and the lineage API are all removed. The kept set matches the AF12 keep list. The 15:08 0/1/0 change only sets the Terraform-side `delete_contents_on_destroy` flag and adds `moved` blocks, which prepares the AF12 delete. I accept it as inside AF12.
- **Judgement: `W9_WIF_PR_TARGET_ENABLED=false`.** Accepted. AF9 covers repository variables. The change only restricts what PRs can do. It is needed after AF12: otherwise a PR would recreate `dbt_ci_pr_*` (R-22) or fail on the missing `w9_drill`. It is recorded, and `gh` confirms the change. Re-enabling needs a new authorization row, as `af12-closeout-20261121.md:25` says.
- **Judgement: `bq rm` of orphan `dbt_ci_pr_57`.** Accepted. AF12 requires deleting every `dbt_ci_pr_*`, and AF3's "CI creates and deletes" describes the normal path, not a ban on close-out cleanup. The name-pattern and `pr=57` label pre-check is recorded but UNVERIFIED here. The resulting state ("dbt_ci_pr_* absent PASS") is an inventory claim. A8 removes the race.
- **AF7.** `DRILL_EMAILS` is 3/6 (recorded). **AF13.** I found no write to W5/W7 resources. The F15 diff reads production through `dataViewer` only.

## Exact checks executed

- `gh run view <id> --json conclusion,status,headSha,headBranch,event,workflowName,createdAt,jobs` for the 10 cited runs. Full `--log` was saved to scratch and searched for `LIVE_FAULT_RESULTS`, `W9_RUN_COST_GUARD`, `Data diff:`, `W9_PII_PROOF`, `Processed records`, `CLEANUP=`, `successfully created`, `##[error]`, and the checkout ref.
- `gh run download` of `fault-matrix-live-f07-f10`, the `week9-run-cost-<run>-*` artifacts for `44872770442`, `44873779562`, `44875222761`, `44881425185`, `44882469242`, `44882607355`, `week9-dataops-summary-56-44882607355`, and `week9-pii-proof-44866987378`, saved to scratch only.
- `gh api repos/…/actions/jobs/136748255564` and `…/136744399247`, plus their job logs (`assert 56 == 55`; `Removed property temp_max_c`).
- `gh run list` for 2026-11-21, to check that the ledger covers every paid-capable W9 run after 14:30 +07. The other runs on that date had their cloud jobs skipped (paused) or are in earlier blocks.
- `gh pr view 56/57/58` and `gh variable list` (read-only).
- `git diff 0cf5a2e..13f5a38 -- cloud/` and the doc diffs. `git diff --check 0cf5a2e..13f5a38` exited 0. No CRLF or BOM in the #58 files.
- Pattern scans for secrets and PII as listed in the matrix.
- `python` arithmetic check of the 14:30 and final cost blocks.
- Local pytest was attempted and not run: pytest is missing in every available interpreter.

## Readiness

**GO with follow-ups for tagging `v0.9.0-week9`** once PR #58's remaining exact-head check (Week 8 CDC compose) finishes green and #58 merges by the normal path. The Major and the Minors are documentation and reproducibility fixes. They can land in #58 before the tag or in the first W10 PR. Major 1 must be done before any W10 Terraform plan or apply.

Do not claim these items done: H-W9-2 mentor review, the Law 91 breach-notification deadline, RFC A1–A8, the settled invoice, Dataplex SKU and C10 storage, and the G4 and email-receipt receipts beyond the operator's or user's record. This is the single G-C verdict; do not call the controller again for this gate.

## Resolution log (integrator, 2026-11-21, same PR #58)
| Finding | Resolution |
|---|---|
| Major: closed-state Terraform variables not recorded | Added `cloud/terraform/week9_dataops/week9_closeout.tfvars.example` and a section in `af12-closeout-20261121.md`; `terraform plan -detailed-exitcode -var-file=week9_closeout.tfvars.example` → exit 0, `No changes`. |
| Minor: W9-05 cites a run that ended `failure` | Row now cites the green #56 run 44882607355, states the R-19 run-level failure of the earlier #57 runs, and limits the cloud build to trusted PRs while `W9_WIF_PR_TARGET_ENABLED=true` (paused since 15:14). |
| Minor: stale forecast in ledger header and RFC §9 | Both now show the final figures (known gross ≈ USD 0.0457, forecast ≈ USD 0.19, cumulative ≈ USD 13.18). |
| Minor: MTTR wording of H-W9-3 | Split into time to restore (1 min 58 s) and MTTR to gate green + RESOLVED (3 min 49 s) in the drill doc, RFC §6 and W9-06. |
| Minor: F-N0 live log lacks `routes` | Open (owner Q): the log line is kept as recorded; the claim stays "12 PASS events, 0 alerts" from the monitor summary. Re-run with `--send-alerts` is a W10 item. |
| Minor: RFC says R-1…R-15 are in `failure_modes.md` | Corrected to the PR descriptions and the operator session log. |
| Note: PM action IDs collide with RFC A1–A8 | Renamed to PM1-A1…PM1-A4. |
| Note: ledger row shows full bytes but total counts the delta | Row now shows the delta and the actual value separately. |
| Note: postmortem-001 gaps 5, 8, 9 called "addressed" | Now "recorded as known limits"; the runbook says `w9_drill` was destroyed at AF12. |
| Other notes (BOM in operator logs, F15 diff is a notice, legal citations, postmortem-000 draft, secret cost in W10) | Accepted as recorded; carried to W10 where relevant. |

