# P7.5 Execution Checklist

Persistent working record for P7.5. The pre-PR baseline is retained above; PR and hosted CI rows are updated as release evidence arrives. Status vocabulary: `PASS`, `PARTIAL`, `BLOCKED`, `NOT_RUN`. Each PASS must cite a source file, command result, or hosted receipt. Optional cloud work requiring fresh approval remains unauthorized and is not a release failure.

## Preflight

| Gate | Status | Evidence / next action |
|---|---|---|
| Clean starting worktree; no user changes to preserve | PASS | Initial `git status --porcelain=v1` empty on `main`. |
| Local main equals fetched origin/main | PASS | Both `2e909487cdeeab265cd8f25b2aa1f715052bdfd4`; fetched origin successfully. |
| Accepted P6.2 and P7.1–P7.4.1 history preserved | PASS | Accepted refs and receipts are retained; no controller verdict, historical receipt, tag, or remote branch was changed/deleted. Final diff review found no commerce or Spark source changes. |
| P7.5 feature branch based on verified main | PASS | `feature/p7-5-airflow-correctness-and-handoff` created from exact origin/main. |
| Syllabus and four required planning documents reviewed | PASS | All 8 syllabus pages and full Master, Prompt A, Prompt B, Prompt C reviewed. |

## P75 acceptance gates

| ID | Requirement | Status | Evidence / remaining work |
|---|---|---|---|
| P75-01 | Accepted Week 7 release preserved | PASS | Historical verdicts/receipts are unchanged; only the additive weather Workflows source removes duplicate dbt tests. Commerce/Spark sources are unchanged; full offline regression passed. |
| P75-02 | Scheduled Airflow run with empty conf resolves a deterministic request | PASS | Empty Params default to scheduled mode and a fixed interval-end minus seven-day date; Airflow 3.4.0 package-level DAG import/Params contract tests passed in an isolated Python 3.11 venv. The Linux Docker runtime was not run. |
| P75-03 | Cloud authorization is separate, explicit, and default OFF | PASS | Unset/false environment gate skips before any cloud client call; project, region, and principal are fixed. |
| P75-04 | Scheduling claims distinguish code from live operation | PASS | The scheduled request contract is tested and documentation explicitly says no hosted/unattended Airflow schedule was demonstrated. |
| P75-05 | Failure event/notification contract is accurate and safe | PASS | Test verifies one redacted `PIPELINE_FAILED` local log event and `external_notification_sent=false`; external delivery remains unverified and was not part of this code-only release scope. |
| P75-06 | Cloud Run/sensor lifecycle has bounded, non-tautological semantics | PASS | Synchronous LRO wait is bounded; redundant post-completion sensor removed; receipt delay, timeout, and validation failures are covered offline. |
| P75-07 | Retryable and terminal failures are classified and tested | PASS | PR #8 code head `4562d3f`: Week 7 PR run `43424336220`, job `131881909659`, passed the real Airflow 3.4 LocalExecutor scheduler harness. Attempt 1 is archived as failed/retry, try 2 succeeds, and both intercepted fake POST attempts use identical args. The 403 control fails on try 1 with one POST and one redacted `PIPELINE_FAILED`; gate OFF skips with zero fake I/O. Local evidence: `D:\DATA_ENGINEER\DataForge_D_Week7_Final\evidence\airflow-scheduler-harness-local-2026-11-13.log`. |
| P75-08 | Weather image and relevant paths are covered in PR CI | PASS | PR #8 code head `4562d3f`: Week 7 PR run `43424336220` and base PR run `43424335661` succeeded; push runs `43424323389` (Week 7, including read-only dbt compile) and `43424323374` (base CI) succeeded. The Week 7 PR run uploaded `airflow-scheduler-harness` (artifact `14035891377`, SHA-256 `3dea5e088cfc7bea30e3e93d71846a3a83672d27e267eea10387d13fd99490b1`). |
| P75-09 | Week 1 public CSV Bash task has offline fixture tests | PASS | Script and guide are included in PR #8; 16 loopback-only fixture tests passed locally and the exact-head PR CI runs passed. This is a P7.5 contribution, not a historical Week 1 PR. |
| P75-10 | README is a concise and accurate portfolio front door | PASS | Root reviewed the verified metrics, four separate domains, Mermaid diagram, safe quickstart, limitations, and links. |
| P75-11 | Evidence index and syllabus map cover Weeks 1–7 / Mini1–3 | PASS | Root reviewed the code/evidence mappings, status vocabulary, and explicit limitations. Week 1 is marked PARTIAL until PR delivery. |
| P75-12 | Mentor handoff and 15 technical defense answers are prepared | PASS | Five handoff docs are present; the defense list has exactly 15 Vietnamese answers; screenshot plan uses authentic receipts only. |
| P75-13 | GitHub hygiene is audited; no unsafe policy mutation | PASS | Read-only settings audit found no rulesets/classic branch rules, no tags/releases, and no open PRs at the snapshot; no settings, issues, branches, or tags changed. |
| P75-14 | FinOps claims distinguish estimate, alert, and actual invoice | PASS | Historical gross estimates are labelled as estimates; settled billing is unknown; no budget or hard cap is claimed. Billing API read returned 403. |
| P75-15 | Exactly one independent final controller review after integration | PASS | The one independent reviewer returned `P75_CONDITIONAL_GO`. Its native Linux Airflow retry condition is satisfied by the `4562d3f` scheduler harness run (`43424336220`, job `131881909659`) and the local metadata evidence above. The original verdict is preserved; no second review was requested. |

### `P75_CONDITIONAL_GO` condition closure

The original controller's only release condition was supported Linux Airflow evidence of a native retry transition for the revised Cloud Run task. The real Airflow 3.4 scheduler harness imported the production Mini3 DAG and patched only `_authorized_session`; its network used `network_mode=none`. On head `4562d3f`, job `131881909659` passed: try 1 was recorded as failed/retry, try 2 succeeded with identical POST arguments, and the 403 and gate-off controls also passed. The PR run uploaded artifact `airflow-scheduler-harness` (`14035891377`). The verdict remains `P75_CONDITIONAL_GO`; this paragraph records satisfaction of its condition and does not replace it with a new controller verdict.

## Phase transitions and external release

| Gate | Status | Evidence / remaining work |
|---|---|---|
| Phase A: `A_CODE_READY` | PASS | Offline regression passed (210 passed, 7 gated skips); local no-egress Airflow 3.4 scheduler harness passed all three scenarios, and the same required harness job passed on Linux CI. See `p75_airflow_correctness.md`. |
| Phase B: `B_PORTFOLIO_READY` | PASS | Portfolio files, Week 1 implementation, path filters, local fixture tests, and documentation checks are integrated on the same branch. Exact-head hosted CI passed on code head `4562d3f`; merge remains pending. |
| Exact-head GitHub PR CI | PASS | PR #8 code head `4562d3f`: Week 7 PR run `43424336220` and base CI PR run `43424335661` succeeded; push runs `43424323389` and `43424323374` succeeded. Read-only dbt compile was skipped on the PR event by its push-only condition and passed on push. |
| Merge and main CI | NOT_RUN | P1 release evidence is complete; execute authorized G1 (mark ready and merge) next. Main-branch CI and local sync remain pending. |
| Prompt C decision memo | NOT_RUN | A+B is not released while PR #8 remains unmerged. After release, perform the authorized read-only architecture/FinOps matrix; no optional cloud writes are authorized. |
| Cloud write / email / budget / recurring schedule | NOT_RUN | Those authorized operations belong to the later Phase 4/5 sequence; no cloud write was made in this PR release harness. |
