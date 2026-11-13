# P7.5 Execution Checklist

Persistent working record for P7.5, captured at the final local review gate before PR creation. Status vocabulary: `PASS`, `PARTIAL`, `BLOCKED`, `NOT_RUN`. Each PASS must cite a source file, command result, or hosted receipt. The exact hosted CI and post-merge state are verifiable in GitHub; optional cloud work requiring fresh approval remains unauthorized and is not a release failure.

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
| P75-05 | Failure event/notification contract is accurate and safe | PASS | Test verifies one redacted `PIPELINE_FAILED` local log event and `external_notification_sent=false`; external delivery remains unverified and unauthorized. |
| P75-06 | Cloud Run/sensor lifecycle has bounded, non-tautological semantics | PASS | Synchronous LRO wait is bounded; redundant post-completion sensor removed; receipt delay, timeout, and validation failures are covered offline. |
| P75-07 | Retryable and terminal failures are classified and tested | PARTIAL | Current HTTP/RPC classifiers, terminal-failure tests, stable retry-argument checks, and task retry-limit assertions pass. The retained Airflow 3.4 `retry_once` receipt is for the separate fixture DAG, not the revised Cloud Run task; no native retry transition for that task is retained or live-tested. |
| P75-08 | Weather image and relevant paths are covered in PR CI | PARTIAL | Both Week 7 path filters and the credential-free image smoke are configured; hosted exact-head CI is pending. |
| P75-09 | Week 1 public CSV Bash task has offline fixture tests | PARTIAL | Script, guide, and 16 offline fixture tests pass locally; PR delivery and hosted CI remain pending. |
| P75-10 | README is a concise and accurate portfolio front door | PASS | Root reviewed the verified metrics, four separate domains, Mermaid diagram, safe quickstart, limitations, and links. |
| P75-11 | Evidence index and syllabus map cover Weeks 1–7 / Mini1–3 | PASS | Root reviewed the code/evidence mappings, status vocabulary, and explicit limitations. Week 1 is marked PARTIAL until PR delivery. |
| P75-12 | Mentor handoff and 15 technical defense answers are prepared | PASS | Five handoff docs are present; the defense list has exactly 15 Vietnamese answers; screenshot plan uses authentic receipts only. |
| P75-13 | GitHub hygiene is audited; no unsafe policy mutation | PASS | Read-only settings audit found no rulesets/classic branch rules, no tags/releases, and no open PRs at the snapshot; no settings, issues, branches, or tags changed. |
| P75-14 | FinOps claims distinguish estimate, alert, and actual invoice | PASS | Historical gross estimates are labelled as estimates; settled billing is unknown; no budget or hard cap is claimed. Billing API read returned 403. |
| P75-15 | Exactly one independent final controller review after integration | PARTIAL | One independent reviewer returned `P75_CONDITIONAL_GO` after the local gates. No second review will be requested. The reviewer requires supported Linux Airflow evidence of a native retry transition for the revised Cloud Run task and green exact-head hosted CI before merge. |

## Phase transitions and external release

| Gate | Status | Evidence / remaining work |
|---|---|---|
| Phase A: `A_CODE_READY` | PASS | Local/code gates passed: 194 tests, 7 expected skips; pinned Airflow Docker runtime is an explicit environment skip. See `p75_airflow_correctness.md`. |
| Phase B: `B_PORTFOLIO_READY` | PASS | Portfolio files, Week 1 implementation, path filters, local fixture tests, and documentation checks are integrated on the same branch. Hosted CI remains a separate release gate. |
| Exact-head GitHub PR CI | NOT_RUN | Requires authenticated PR creation; record each job and run ID. |
| Merge and main CI | NOT_RUN | Merge only if policy and review requirements permit. |
| Prompt C decision memo | NOT_RUN | Documentation/read-only architecture and FinOps analysis only. |
| Cloud write / email / budget / recurring schedule | BLOCKED | NOT AUTHORIZED; no such operation is required for A+B. |
