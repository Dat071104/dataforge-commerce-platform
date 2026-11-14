# Lane E — Portfolio, syllabus traceability, and demo voice

**Snapshot refreshed:** 2026-11-14 from the integrator's latest state update. This Lane E branch is still based on the earlier 95f89b4 integration and has not been rebased onto the B/D merge commits.

## Scope delivered

- Reworked the canonical W1-01…W7-08 coverage table and evidence index. Every syllabus row has a bounded evidence pointer and a MET, PARTIAL, NOT_RUN, or MENTOR_CONFIRMATION_PENDING status.
- Added an engineering decision record in first person with an explicit AUTHOR REVIEW REQUIRED marker. The draft is evidence-based but is not author sign-off.
- Updated the Vietnamese Week 1–7 demo script and Week 7 demo pack to distinguish local, CI, historical live, and mentor/user-reported evidence.
- Added a cost table that separates lane incremental spend, historical gross usage estimates, planned lower bounds, current live-resource cost, and settled billed spend.
- Added a course tracker with official or primary learning links. Completion and evidence columns are blank.

## Evidence snapshot and open integration state

- Lane B PR #9 merged at 9bca18c. Lane D PR #13 merged normally at f4d340ff151557040d85e1688a9e0f94caa2a8c5.
- D exact-head PR checks passed: Week 7 attempt 2 run 43584910006 had eight successful jobs and one expected keyless-compile skip; Airflow job 132422133934 passed all six scenarios. Its first attempt timed out on the fifth synthetic backfill date; the unchanged retry passed. The exact failed task state/root cause was not captured and no code/assertion changed. Base Postgres job 132417202516 includes the q10 EXPLAIN plans. The planner used the baseline index; no speedup is claimed.
- Merge-SHA base CI 43606510616 and Week 7 run 43606510673 passed on f4d340ff151557040d85e1688a9e0f94caa2a8c5. Airflow job 132482197676 succeeded and artifact 14118655954 (SHA-256 9a0a8d20c7f1599a8b4d722a81b8eefa84abd3bf9eea7b89cb412a87c7068d52) was uploaded. Local main and origin/main are clean at the merge SHA; this Lane E branch remains behind and needs rebase/integration.
- Cloud inventory and actual hourly run-rate remain unknown because H5/R1 reauthentication/inventory is blocked. No GCP resource is confirmed currently running, but that is not proof that none exists. Lane D created no GCP resource; Lane E made no cloud call.
- No Lane E GitHub or cloud action was performed. This branch still needs integrator rebase/review before its PR and final main verification.

This is a point-in-time snapshot. Refresh the checklist and CI state before presenting. Older receipts and prior Lane E notes remain historical evidence and must not be rewritten as current remote state.

## Focused verification

For this refresh, all local Markdown links in the updated coverage, Vietnamese demo script, cost table, and Lane E report resolved. The coverage matrix has 45 unique IDs with 13 MET, 22 PARTIAL, 8 NOT_RUN, and 2 MENTOR_CONFIRMATION_PENDING. The demo snapshot states the merged B/D commits and successful merge-SHA base/Week 7 CI. The cost table preserves unknown inventory/hourly rate and settled spend; AUTHOR REVIEW REQUIRED remains present in the decision draft. No product tests, GitHub action, or cloud operation was run by Lane E.

## Handoff to the integrator

- E6 GitHub metadata, release/tag settings, repository description/topics, ruleset, and branch cleanup remain outside this lane. Verify each exact SHA before changing remote metadata or deleting a branch.
- README front-door work is present on this branch as commit 5c9063a; review it against the final CI before integration. Workflow/docs publication remains integrator-owned; keep Pages publication disabled unless its specific authorization is present.
- The older integration snapshot in docs/EVIDENCE_INDEX.md, docs/ENGINEERING_DECISIONS.md, and the Week 7 checkpoint walkthrough/architecture still describes B/D as pending. The acceptance checklist tells presenters to check current CI but was not date-refreshed. These paths were outside this refresh scope; update them before using the full demo pack as a current status report.
- Ask the author to review docs/ENGINEERING_DECISIONS.md before presenting first-person reflections. The prepared walkthrough is not evidence that a mentor demo or review occurred.
- Keep unsettled project billing and current VM inventory explicitly unknown until an authorized current billing/resource receipt exists.

## RCA log

### Coverage/evidence-index target mix-up (2026-11-14)

- **Symptom:** The attempted exact-line replacement of the D-pack checklist link failed its presence guard; no edit occurred. Readback then showed that docs/SYLLABUS_COVERAGE.md ended with Evidence Index content rather than its expected cross-cutting coverage section.
- **Reproduction:** Get-Content docs/SYLLABUS_COVERAGE.md -Tail 12 displayed the evidence-index regression command and did not contain the expected checklist-note line.
- **Hypotheses:** A path mix-up or a shared PowerShell variable used for two outputs. The prior writer assigned the Evidence Index text to the same variable and wrote it to both SYLLABUS_COVERAGE.md and EVIDENCE_INDEX.md.
- **Root cause:** The two documents shared the final content value, so the Evidence Index text overwrote the intended coverage content.
- **Fix:** Rebuild SYLLABUS_COVERAGE.md in a distinct variable, write it only to that path, then read back its header, cross-cutting footer, and exact IDs. Keep EVIDENCE_INDEX.md independently written.
- **Guard:** Run exact ID/status counts and internal Markdown-link checks for both files after the write; inspect the first and last sections before staging.

### RCA append command parse failure (2026-11-14)

- **Symptom:** The first attempt to append the RCA above failed in the JavaScript parser before PowerShell launched; no report write occurred.
- **Reproduction:** The embedded PowerShell here-string contained Markdown inline backticks inside the outer JavaScript template literal.
- **Hypothesis:** PowerShell quoting versus outer JavaScript termination. The JavaScript SyntaxError identifies the latter; the shell was never started.
- **Root cause:** Unescaped Markdown backticks prematurely terminated the JavaScript template literal.
- **Fix:** Reissue the append with plain text and no backtick characters in the embedded content.
- **Guard:** Scan tool-call source for template-literal delimiters before calling the shell; read back the appended report section.
### Focused Markdown count and whitespace check (2026-11-14)

- **Symptom:** Local-link resolution passed, the coverage ID count was 45, Q&A count was 20, and course completion/evidence fields were blank. The status counter emitted errors and did not report category totals; the whitespace scan identified trailing Markdown hard-break spaces on the Q&A answer lines.
- **Reproduction:** The PowerShell script called GetValueOrDefault on a Hashtable, then its trailing-whitespace scan reported each Q&A answer line ending in two spaces.
- **Hypotheses:** A coverage-status mismatch versus a PowerShell compatibility issue, and accidental whitespace versus intentional Markdown hard breaks. The hashtable method is not available in this Windows PowerShell version; the Q&A lines use two spaces only to force line breaks.
- **Root cause:** The validator used an unsupported helper method, and the Q&A used a Markdown hard-break style that fails the repository whitespace check.
- **Fix:** Count statuses with Hashtable.ContainsKey and remove trailing hard-break spaces, leaving blank lines between questions and answers.
- **Guard:** Rerun the status counts, exact ID count, Q&A count, blank course-field check, link resolution, trailing-whitespace scan, and git diff --check. Make validator errors terminating.
### Focused validator wrapper interpolation errors (2026-11-14)

- **Symptom:** The next validator call failed in the JavaScript wrapper with ReferenceError: f is not defined before PowerShell launched; no whitespace repair or validation ran.
- **Reproduction:** The embedded PowerShell diagnostic used the form dollar-f colon dollar-n inside the outer JavaScript template literal. An attempt to append this RCA with the same template style also failed during JavaScript parsing; neither failed call reached PowerShell or wrote a file.
- **Hypothesis:** Shell variable expansion versus JavaScript template interpolation. The wrapper ReferenceError and parse error confirm the outer JavaScript interpreted the embedded expression first.
- **Root cause:** PowerShell variable interpolation syntax conflicted with JavaScript template-literal interpolation in tool-call source.
- **Fix:** Build the PowerShell diagnostic string by concatenating the variable names and line number; rerun the same focused checks.
- **Guard:** Avoid dollar-brace expressions in exec template literals unless intentionally escaped; confirm shell exit status and expected summary output.

### Stale integration-validator expectation (2026-11-14)

- **Symptom:** The final focused validator stopped at a snapshot assertion after local links, 45 unique IDs, and the 13/22/8/2 status counts passed. No file changed.
- **Reproduction:** The assertion still expected the text “still in progress,” copied from the earlier task message, while the newer checklist at 21:53 records Week 7 merge-SHA CI as passed.
- **Hypothesis:** The docs had regressed versus a failed CI run, or the validation token was stale. The latest checklist RESUME_POINT and session log both record run 43606510673 passed and Airflow job 132482197676 succeeded.
- **Root cause:** The validator expected an obsolete intermediate state after the evidence snapshot had been updated.
- **Fix:** Replace the stale assertion with checks for both successful merge-SHA runs and the Airflow terminal job.
- **Guard:** Read the latest local checklist snapshot immediately before final validation and assert only its observed status text.
