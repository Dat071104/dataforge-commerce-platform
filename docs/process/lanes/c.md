# Lane C — Cloud Ops, FinOps, and IaC

## Work report

**Branch:** `feat/w7-cloud-ops`, based on main SHA `7cd204caa29e17c35137272d9ee3b406caef17eb`. Code commit `6c029b5d315ff836a4b3a34211ac2abc73f7e90a` contains the Lane C preparation. It is local only; no push, PR, or cloud action.

### Changed files

- `cloud/terraform/dev/main.tf`, `variables.tf`, `versions.tf`, `dev/.gitignore`: dry-run-first cleanup policies for Week-5 and Week-7 Artifact Registry packages, explicit live digest lists, and a staged GCS backend block for C10.
- `cloud/terraform/state_backend_bucket/`: dedicated bucket bootstrap with versioning, uniform access, public access prevention, and destruction protection.
- `cloud/terraform/week7_ops/`: separate C2 budget and C3 Workflow/Airflow alert policies root. Flags default off; C9 email is a sensitive input.
- `cloud/terraform/airflow_vm/`: separate C4/C8 state root for an IAP-only, no-external-IP VM, Cloud NAT egress, service-account logging, Secret Manager access, and 120-hour destroy-by guard. Secrets use the provider write-only argument.
- `labs/spark_nyc_taxi/managed/`: generation-pinned staging manifest, local independent oracle, Dataproc Serverless driver, cost preflight, plan-only-by-default submit wrapper, and tests.
- `docs/cloud/week7/ops/README.md`: phase ordering, exact C4/C7 pricing math and caps, C10 sequence, C11 immutable-tag limitation, and unblocks.
- `docs/process/lanes/c.md`: lane report and RCA notes.

### Validation

- `python -m unittest discover -s labs/spark_nyc_taxi/managed/tests -v` — **12 passed**.
- `python -m compileall -q labs/spark_nyc_taxi/managed` — **PASS**.
- PowerShell parser on `labs/spark_nyc_taxi/managed/submit.ps1` — **PASS**.
- Plan-only submit wrapper with synthetic GCS URIs/SHA/generations and a caller-supplied USD 1.00 remainder — **exit 0**, estimated USD `1.720548`, status `PASS_WITHIN_80_PERCENT_STOP`. This is a synthetic guard test only, not a project estimate or pre-submit clearance; `-Submit` was not used and no gcloud command ran.
- `python scripts/week7_secret_scan.py` — **PASS**, 0 findings across 522 files.
- `git diff --check` — **PASS**.
- `Get-Command terraform` found no Terraform CLI; Python `hcl2` is unavailable. Terraform fmt/init/validate/plan were **NOT RUN**; no tool was installed.
- Existing local Spark fixture suite was **NOT RUN**: the pinned Python base digest was not cached. No image pull was attempted. The managed Spark contract/cost tests above ran locally without Spark or network.
- CI run IDs: **none**; the lane branch was not pushed.

### R1 read-only results and blockers

- Dot-sourcing the isolated DataForge helper selected project `dataforge-p7-lab-d0f725`.
- Artifact Registry `dataforge-week7` describe succeeded and reported `476.891 MB`; cleanup-policy fields were unset/null.
- `gcloud compute instances list --project=dataforge-p7-lab-d0f725 --quiet` returned `PERMISSION_DENIED` with `compute.googleapis.com` disabled. VM, disk, and firewall state therefore remains unknown.
- `gcloud billing projects describe dataforge-p7-lab-d0f725` returned `PERMISSION_DENIED` with `cloudbilling.googleapis.com` disabled. An earlier parent R1 probe reported `billingEnabled=True`; the CLI visibility discrepancy and billed amount remain unresolved.
- Two read-only Cloud Run image projections returned blank/null under the attempted gcloud field path. No current digest was inferred; the cleanup list is seeded from retained receipts and must be refreshed via a verified field-only query before dry-run.
- No API was enabled and no IAM role changed. Terraform ownership/state was not inspected because the CLI is unavailable.

### Cost methodology

- **C4 fixed-resource lower bound:** e2-medium at USD `0.03350571/hour` × 120 hours = `4.0206852`; 30 GiB standard disk at USD `0.000054795/GiB-hour` × 30 × 120 = `0.197262`; one-VM Cloud NAT at USD `0.0014/hour` × 120 = `0.168`; one NAT IP at USD `0.005/hour` × 120 = `0.600`. Known subtotal = **USD 4.9859472**. This is not expected use or worst case; NAT processing, outbound transfer, logs, and staging remain unknown. C4 USD 8 cap stops at USD 6.40; about USD 1.414 remains above the known subtotal for all unpriced use.
- **C7 compute/shuffle bound:** 12 standard DCUs × USD `0.06/DCU-hour` × 0.5 hour × 2 attempts = **USD 0.72** compute. An illustrative 10 GiB shuffle bound at USD `0.000054795/GiB-hour` for two 30-minute attempts adds `0.00054795`. This is not a full pre-submit gross upper bound; GCS staging/output storage and network transfer need measured sizes and official rates. C7 USD 5 cap stops at USD 4.00.
- Official rates: [E2 VM pricing](https://cloud.google.com/products/compute/pricing/general-purpose?hl=en), [Persistent Disk pricing](https://cloud.google.com/compute/disks-image-pricing), [VPC/Cloud NAT pricing](https://cloud.google.com/vpc/network-pricing), [Managed Spark pricing](https://cloud.google.com/products/managed-service-for-apache-spark/pricing).

### Open risks and exact unblocks

- **Terraform validation:** run Terraform `1.17.1` with Google provider `8.9.0` in approved CI across `cloud/terraform/dev`, `cloud/terraform/week7_ops`, `cloud/terraform/airflow_vm`, and `cloud/terraform/state_backend_bucket`; resolve syntax/schema errors before any plan.
- **C10:** back up existing local state, create/verify the dedicated bucket, assign unique backend prefixes, migrate existing dev state with `terraform init -migrate-state`, then require plans to show no changes. None of this ran.
- **C2/C3:** billing account ID and current notification service state need R1 confirmation. C3 filters need one actual Workflow failure log and a real Airflow `gcplogs` sample; `airflow-scheduler` label must match Lane A. Monitoring/Logging APIs were not enabled.
- **C4/C8:** use the verified existing VM service account, Lane A image digest/runtime bundle/startup script, a live-verified non-overlapping subnet, protected backend, generated secrets, and a complete cost bound below USD 6.40 before apply. Destroy only the `airflow_vm` root by the deadline; C2/C3 remain in `week7_ops`.
- **C7:** acquire only January 2024 source under C7, verify SHA/bytes, stage with create-only generation preconditions, create sanitized manifest and local oracle, bound GCS/network remainder from measured sizes, and submit at most two batches only if total worst case is below USD 4.00. No source was downloaded/staged and no batch/UI screenshot was created.
- **C11:** keep dry-run on. The historical Week-5 cleanup receipt `artifact_registry_cleanup.json` reports `BLOCKED_BY_TAG_IMMUTABILITY` and `FAILED_PRECONDITION` when deleting tagged `week5-20261110-r1`; this draft has no tagged-delete rule and only targets old untagged versions. Refresh live digests and confirm Terraform state ownership before dry-run; immutable tagged history may remain beyond the retention count.
- Shared `docs/releases/v1.0-local.md` is integrator-owned; append the exact lane test commands/results during integration rather than editing it here.

### Cloud boundary

No cloud write, API enablement, Terraform apply/state migration, secret or secret-version creation, Artifact Registry cleanup apply/delete, VM, schedule, notification, external data upload/download, Dataproc batch, or paid action occurred in Lane C.

## RCA log

### Terraform secret-version variable patch context mismatch

- **Symptom:** `apply_patch` rejected a context that expected `airflow_secret_payloads` to be followed immediately by `enable_budget`; no file was changed.
- **Expected vs actual:** the patch assumed `airflow_secret_data_version` was missing. Inspection showed it was already present exactly once in `cloud/terraform/week7_ops/variables.tf`.
- **Reproduction:** `rg -n -A 25 'airflow_secret_payloads|enable_budget' cloud/terraform/week7_ops/variables.tf` showed the version variable and its positive-version validation.
- **Hypotheses:** (1) prior patch already added the block; (2) concurrent worktree edit. The file content confirms (1); the lane C worktree has one owner.
- **Root cause:** the attempted follow-up duplicated a block already included in the initial variables file.
- **Fix:** no second patch; retain the existing single variable.
- **Guard:** verify exactly one declaration before continuing and run `git diff --check` at the end.

### Terraform file patch contained a duplicate target

- **Symptom:** `apply_patch` rejected the multi-file update with `invalid patch: multiple operations target .../week7_ops/secrets.tf`; no HCL changes from that patch were applied.
- **Expected vs actual:** the patch intended one `secrets.tf` addition, but the patch text contained that same path twice.
- **Reproduction:** the failed single `apply_patch` call; `git status` confirms only the earlier C11 edits and lane report are present.
- **Hypotheses:** duplicate patch target vs path handling; the reported duplicate destination confirms the duplicate target.
- **Root cause:** `secrets.tf` was included once before `alerts.tf` and again after it.
- **Fix:** after this RCA, reissue a patch with each path exactly once.
- **Guard:** list patch paths before applying; run `git diff --check` and review the changed-file list afterward.

### Lane report RCA append path mismatch

- **Symptom:** a follow-up `apply_patch` could not find `docs/process/lanes/c.md`; no report file was changed.
- **Expected vs actual:** the patch path was relative to the repo worktree, but `functions.exec` applies patches relative to `D:\DATA_ENGINEER`.
- **Reproduction:** the patch returned `The system cannot find the path specified` for `D:\DATA_ENGINEER\docs\process\lanes\c.md`.
- **Root cause:** the patch path omitted the `DataForge_worktrees/lane-c` prefix.
- **Fix:** use the verified worktree-qualified path for this report and keep all source edits inside lane C.
- **Guard:** check the absolute target exists before appending or patching.
### Managed Spark README JavaScript escaping RCA

- **Symptom:** the README patch call failed with `SyntaxError: Invalid Unicode escape sequence` before `apply_patch`; no README was written.
- **Expected vs actual:** intended to add a PowerShell example; the outer JavaScript parser rejected a Windows backslash sequence in the embedded command text.
- **Reproduction:** the failed `functions.exec` cell containing a literal `\labs` fragment.
- **Root cause:** an unescaped backslash was included in a JavaScript string.
- **Fix:** use forward-slash paths in the example after this RCA.
- **Guard:** keep patch source free of Windows backslash escapes and run `git diff --check` after writing.

### Staging manifest import syntax RCA

- **Symptom:** source inspection found invalid Python syntax from labs.spark_nyc_taxi.download import MONTHLY_URL if False else None in the new staging helper; it was not run.
- **Expected vs actual:** the helper only needs local constants; the conditional import is not valid Python grammar.
- **Reproduction:** python -m py_compile labs/spark_nyc_taxi/managed/stage_manifest.py would fail at that line (not yet run).
- **Hypotheses:** import typo vs module import-time environment issue; parsing evidence points to syntax only.
- **Root cause:** an unnecessary placeholder import was typed as a Python conditional import.
- **Fix:** after this RCA, remove the unused line and keep the explicit local URL constants.
- **Guard:** run py_compile, focused unit tests, and the final diff check.


### Managed Spark README patch context mismatch

- **Symptom:** apply_patch rejected the README context; the paired submit.ps1 change was atomic and also did not apply.
- **Expected vs actual:** the patch expected the staging paragraph to end after generation capture; the actual README also contains a final sentence describing the submit wrapper's read-only generation recheck.
- **Reproduction:** rg -n -C 1 'staging step|StageBucket|SourceSha256|SourceGeneration|OutputUri' ... showed the complete changed paragraph and the unchanged StageBucket validation.
- **Root cause:** patch context was copied from an earlier draft before the post-staging generation check was added.
- **Fix:** after this RCA, replace only the unique staging sentence and update the StageBucket validation to accept a bucket URI with no object path.
- **Guard:** re-read the complete context, inspect both files, and run git diff --check plus the plan-only wrapper test.


### C7 submission wrapper source generation range RCA

- **Symptom:** the plan-only wrapper test exited 1 before cost preflight with Cannot validate argument on parameter 'SourceGeneration' because the validation limits were Int32 while the parameter was Int64 and the supplied GCS generation was larger than 32 bits.
- **Expected vs actual:** the wrapper should accept positive 64-bit object generations; PowerShell rejected the range attribute before running Python or invoking gcloud.
- **Reproduction:** invoke submit.ps1 without -Submit using -SourceGeneration 1700000000000000 and -ZoneGeneration 1700000000000001 plus a bounded cost estimate.
- **Hypotheses:** invalid generation format vs parameter validator type mismatch; the error explicitly identifies the range types and occurs before argument validation, confirming the latter.
- **Root cause:** [ValidateRange(1, 2147483647)] limits are Int32 and conflict with the Int64 generation parameter.
- **Fix:** after this RCA, replace the range attributes with a positive-value ValidateScript that preserves Int64 values.
- **Guard:** rerun the plan-only wrapper test; it must return its JSON plan and exit 0 without calling gcloud when -Submit is absent.


### C11 immutable-tag cleanup design RCA

- **Symptom:** code review found the new cleanup draft included DELETE for tagged versions older than 30 days, while the existing Week-5 cleanup receipt records BLOCKED_BY_TAG_IMMUTABILITY and a prior tagged delete returned FAILED_PRECONDITION for week5-20261110-r1.
- **Expected vs actual:** cleanup must preserve at least five tagged versions and all live digests; the draft attempted a tagged delete that the current immutable-tag configuration rejects.
- **Reproduction:** inspect docs/cloud/week5/artifact_registry_cleanup.json and docker_config.immutable_tags=true in cloud/terraform/dev/main.tf for both managed repositories.
- **Hypotheses:** immutability applies only to tag movement vs immutability also prevents deletion. The retained error receipt directly confirms deletion is blocked.
- **Root cause:** the draft added a tagged delete policy without accounting for immutable tag protection.
- **Fix:** after this RCA, remove tagged deletion and retain only dry-run plus untagged cleanup; keep the most recent five versions and explicit live digests.
- **Guard:** retain dry-run by default; inspect a fresh artifact cleanup dry-run before any non-dry-run policy and never attempt a tagged-version delete.


### Week 7 ops runbook patch context RCA

- **Symptom:** apply_patch rejected the README context for the C7 pricing paragraph; no README change was written.
- **Expected vs actual:** the patch used earlier wording, while the current line says Missing inputs or a total at/above USD 4.00 block submission. and begins with the planned standard profile.
- **Reproduction:** rg -n -C 1 'cost gate|C11|provider|stop threshold' docs/cloud/week7/ops/README.md showed the exact line.
- **Root cause:** stale patch context copied before the last README edit; no concurrent agent owns this file.
- **Fix:** after this RCA, replace only the uniquely located C11 paragraph and leave the already accurate C7 cost paragraph unchanged.
- **Guard:** reread the updated C11 paragraph and run git diff --check.


### C8-before-C4 toggle ordering RCA

- **Symptom:** self-review found enable_secrets=true could not be planned independently because its validation required enable_vm=true, contradicting the authorized Phase 4 order C8 before C4.
- **Expected vs actual:** C8 should create Secret Manager objects/access for the already verified VM service account before the VM exists; the current validation coupled secrets to VM creation.
- **Reproduction:** inspect the cross-variable validation blocks in cloud/terraform/week7_ops/variables.tf; no Terraform plan was run because the CLI is unavailable.
- **Hypotheses:** resource dependency vs toggle validation; the toggle condition itself is the blocker.
- **Root cause:** the initial toggle validation disallowed the prescribed separate C8 deployment step.
- **Fix:** after this RCA, allow enable_secrets with only the verified existing service account; keep enable_vm requiring enable_secrets=true and all C4 image/network/deadline inputs.
- **Guard:** after the fix, statically inspect the toggles so C8 can plan alone and C4 still cannot plan without the secrets inputs.

### R1 Cloud Run image projection query

- **Symptom:** `gcloud run jobs describe` for both weather jobs returned exit 0 but the requested `template.template.containers[0].image` projection was blank.
- **Expected vs actual:** expected the current image references; actual output did not expose a value, so no current image digest was inferred from that command.
- **Reproduction:** the read-only command used `--format=value(template.template.containers[0].image)`.
- **Hypotheses:** field path mismatch vs jobs having no template/container; the command's value projection is not sufficient to discriminate.
- **Root cause:** the diagnostic format path did not yield the nested image in this gcloud schema; exact cause still needs read-only JSON projection.
- **Fix:** after this RCA, use `--format=json` captured to a PowerShell object and print only `template.template.containers.image` values.
- **Guard:** assert each job returns exactly one non-empty digest-pinned image and compare with the retained image receipts; suppress the rest of the job document.

### R1 Compute/Billing API visibility

- **Symptom:** Compute instance inventory failed with `PERMISSION_DENIED` and the API-disabled notice; billing project describe failed with `PERMISSION_DENIED` and `Cloud Billing API has not been used in project ... or it is disabled`.
- **Expected vs actual:** read-only inventory expected VM/billing details; no VM list or billed amount was returned by these probes.
- **Reproduction:** isolated-target commands `gcloud compute instances list --project=dataforge-p7-lab-d0f725 --quiet` and `gcloud billing projects describe dataforge-p7-lab-d0f725`.
- **Hypotheses:** missing IAM vs disabled services; exact error bodies explicitly state compute.googleapis.com and cloudbilling.googleapis.com are disabled, so this is service state, not an IAM denial.
- **Root cause:** target APIs are disabled for this identity/project view; no write was attempted.
- **Fix:** no action in Phase 2; unblock the reads at the authorized Phase 4 preflight by enabling only the required APIs under C1, then repeat the read-only inventory.
- **Guard:** never enable APIs solely to get a nicer snapshot; classify each failure before any C1 change and do not change IAM.

### R1 current image path projection RCA

- **Symptom:** isolated gcloud run jobs describe --format=json returned exit 0 for both Week-7 jobs, but the inspected template.template.containers[0].image property was null; no current image digest was recorded from this probe.
- **Expected vs actual:** expected one digest-pinned image per job; the parsed container array had one item but its image property was null under this PowerShell projection.
- **Reproduction:** describe the two jobs with --format=json, then project only template.template.containers[].image in a PowerShell object.
- **Hypotheses:** CLI JSON shape differs from assumed nested property, or the PowerShell conversion sees a different container type. The current output does not distinguish them.
- **Root cause:** image-field mapping remains unknown; do not replace the retained digest evidence with an inferred value.
- **Fix/unblock:** use a sanitized property-key inspection or the official Run Jobs REST representation to identify only the image field; no full environment/job document should be emitted.
- **Guard:** require exactly one non-empty image per job, verify @sha256: form and compare against the cleanup keep list before any C11 dry-run.


### R1 Cloud Run JSON key inspection RCA

- **Symptom:** the follow-up PowerShell JSON-key inspection stopped with You cannot call a method on a null-valued expression; no cloud state changed and no image value was emitted.
- **Expected vs actual:** expected only property names/types from a read-only job response; the assumed template.template.containers[0] object was null in this converted shape.
- **Reproduction:** the isolated gcloud run jobs describe --format=json output followed by the PowerShell nested-property inspection.
- **Hypotheses:** job JSON uses a different nesting than assumed; gcloud outputs a special object shape; local conversion/indexing syntax is wrong. Evidence confirms only the initial nested lookup is null; exact response shape was not printed.
- **Root cause:** the diagnostic projection used an unverified nested property path, then dereferenced null.
- **Fix/unblock:** stop further image-projection retries in this lane; use the retained iam_cost_cleanup.md receipt for the current seeded digests, and let integrator perform a bounded field-only read via a verified schema/API path before any C11 dry-run.
- **Guard:** no full job JSON/environment output; inspect returned property names before reading any value and require one digest-pinned image before cleanup.


### Terraform state lifecycle separation RCA

- **Symptom:** self-review found the first week7_ops root co-located the 5-day VM/secrets with permanent budget and alert policies.
- **Expected vs actual:** Phase 5 requires destroying the VM and its secrets while retaining C2/C3 resources; one root's ordinary destroy would plan to remove all of them.
- **Reproduction:** compare the planned week7_ops resource grouping with Master Phase 4/5 order: terraform destroy VM module, disable/delete VM secrets, keep alert policies.
- **Hypotheses:** use -target for VM teardown vs split lifecycle roots; -target is brittle and leaves partial-state reasoning, while root separation directly matches retention boundaries.
- **Root cause:** the initial Terraform root mixed short-lived VM/secrets and permanent budget/alert lifecycles.
- **Fix:** after this RCA, split C4/C8 network/VM/secrets into a dedicated cloud/terraform/airflow_vm root/state prefix and leave C2/C3 in week7_ops.
- **Guard:** verify the Week-7 operations root contains no VM/secrets resources and the VM root contains no budget/alert policies; no apply/destroy in this lane.


### Ops root split block-selection RCA

- **Symptom:** the checked rewrite of week7_ops/main.tf stopped before writing because the retained prefix did not contain the C2 budget resource; main.tf stayed unchanged while unused VM variables were removed from variables.tf.
- **Expected vs actual:** expected the C4 section to start after the budget; the first google_project_service.compute block appears before the notification channel and budget.
- **Reproduction:** rg -n '^resource ' cloud/terraform/week7_ops/main.tf shows compute API at line 32 and budget at line 74.
- **Hypotheses:** marker-order mismatch vs file mutation; live read confirms marker-order mismatch and no write to main.tf.
- **Root cause:** the script used a simple truncate-at-first-compute marker even though API resources precede permanent C2/C3 resources.
- **Fix:** after this RCA, rewrite the small ops root with only budget/alert resources instead of truncating by marker.
- **Guard:** verify the ops root has no compute, VM, or secrets resources and still includes C2/C3 before any Terraform invocation.


### Ops root split JavaScript cell RCA

- **Symptom:** functions.exec returned SyntaxError: Missing initializer in const declaration before invoking PowerShell; no files changed.
- **Expected vs actual:** the lane split rewrite should run in a PowerShell here-string; the outer JS parser rejected the literal multiline double-quoted cmd value.
- **Reproduction:** the failed functions.exec cell contained unescaped literal newlines inside a JavaScript double-quoted string.
- **Root cause:** the command was constructed as a regular JS string rather than an escaped string or template literal.
- **Fix:** after this RCA, use a template literal and avoid ${...} interpolation in HCL by using format() for the one Terraform interpolation.
- **Guard:** check the tool cell parses before shell invocation and inspect git status after the rewrite.


### Week-6 Spark fixture venue RCA

- **Symptom:** local docker image inspect python:3.11.18-slim-bookworm@sha256:a83ba18aef0f865b1a4a611c2cf460fe446f2795673bbb9fe43be570439e3b39 returned no image (exit 1); the local labs/spark_nyc_taxi/ci.ps1 suite was not started.
- **Expected vs actual:** expected to use the cached project Spark base; the pinned Dockerfile base is not present in the local image store.
- **Reproduction:** the docker image inspect command above. No pull or test container was started.
- **Hypotheses:** cache contains only the derived image, or Docker local image metadata does not retain the pinned base tag/digest. The inspected image was absent; the exact cache reason is not known.
- **Root cause:** ENV — pinned base image is not locally available; a fixture run would pull external software.
- **Fix/unblock:** no retry in this lane; run the existing Spark fixture suite in approved CI or after an authorized/preloaded image is available.
- **Guard:** do not run docker compose build until the pinned base is present; rely on the new local pure-contract tests and compile checks meanwhile.


### C4 cost wording patch context RCA

- **Symptom:** apply_patch rejected a C4 cost summary context; no README change occurred.
- **Expected vs actual:** the intended line was correct through the worst-case sentence, but the actual line continues with official pricing links.
- **Reproduction:** the failed patch matched only the sentence prefix and omitted the trailing citation links.
- **Hypotheses:** content drift vs a partial line; rg confirmed one complete line with citations.
- **Root cause:** patch context omitted the line's trailing source citations.
- **Fix:** after this RCA, use a unique phrase replacement that preserves the citations.
- **Guard:** read the full resulting line and run git diff --check.

### Lane report replacement JavaScript syntax RCA

- **Symptom:** a report-update `functions.exec` cell failed with `SyntaxError: Missing initializer in const declaration` before PowerShell ran; no report or source file changed.
- **Expected vs actual:** the report text should be written through a PowerShell here-string, but the outer JavaScript source contained literal newlines inside a double-quoted string.
- **Reproduction:** the failed cell that constructed `const cmd = "...` across physical lines.
- **Hypotheses:** PowerShell parse issue vs JavaScript parse issue; tool error occurred before `exec_command`, confirming JavaScript parsing.
- **Root cause:** a multiline command was embedded as a raw newline in a JS quoted string.
- **Fix:** after this RCA, construct the command as escaped `\n` text or use individually quoted line-array entries; do not use a multiline JS double-quoted literal.
- **Guard:** first run `git diff --check` and verify only the lane report changes before committing.

### Lane report placeholder replacement RCA

- **Symptom:** the checked PowerShell .Contains() replacement found no exact ## Work report + Pending. substring, so the report write was aborted.
- **Expected vs actual:** Get-Content -TotalCount 10 shows the placeholder visually, but the raw text line-ending/whitespace sequence did not match the exact string.
- **Reproduction:** the failed Contains() guard; no content was written.
- **Hypotheses:** CRLF/LF normalization or trailing whitespace; the visible line differs from the expected byte/string sequence.
- **Root cause:** exact multiline string matching was too strict for this file's newline/whitespace representation.
- **Fix:** after this RCA, replace via a counted multiline regex anchored to the Work report heading and placeholder line.
- **Guard:** require exactly one regex match, then read back the first report lines and git diff --check.

### Lane report duplicate heading RCA

- **Symptom:** after replacing the placeholder, the report contains two consecutive `## Work report` headings.
- **Expected vs actual:** expected one heading; actual output has one retained prefix plus a second heading at the beginning of the inserted report body.
- **Reproduction:** `Get-Content docs/process/lanes/c.md -TotalCount 8`.
- **Hypotheses:** regex replacement boundary vs duplicated heading in replacement payload; the replacement payload itself began with the heading, confirming the duplicate.
- **Root cause:** the replacement prefixed `## Work report` and the report body also contained it.
- **Fix:** after this RCA, remove exactly one consecutive heading using a match-count-checked replacement.
- **Guard:** assert exactly one `## Work report` heading remains and run `git diff --check`.
### Lane report control-character and line-ending RCA

- **Symptom:** `git diff --cached --check` flagged trailing carriage returns on the lane report; a character scan found U+000C, U+0007, U+001B, U+000B, and lone carriage returns in earlier appended RCA text.
- **Expected vs actual:** the Markdown report should be plain UTF-8 text with LF endings; embedded JavaScript escaping converted some backslash-letter pairs into control characters, and PowerShell appended CRLF.
- **Reproduction:** the staged-diff check plus a read-only scan for C0 control characters.
- **Hypotheses:** terminal rendering only vs control bytes on disk; byte-level character scan confirms the latter.
- **Root cause:** report text was built in a JavaScript quoted string where `\a`, `\f`, `\e`, `\v`, and `\r` were interpreted as control characters, then saved with CRLF.
- **Fix:** after this RCA, unstage the report, normalize line endings to LF, replace those specific control bytes with their intended letters, and read back affected entries.
- **Guard:** require zero control characters other than LF and rerun both staged and unstaged `git diff --check` before committing.