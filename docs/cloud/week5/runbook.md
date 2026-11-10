# Week-5 operator runbook

## Fixed target and source setup

This runbook is limited to `dataforge-p7-lab-d0f725` / `955038620072`, `us-central1`, and `dataforge-p7-lab-d0f725-bronze`. The source simulator is separate from the accepted application database.

~~~powershell
docker compose --project-name dataforge-week5-source `
  --file labs/operational_source/compose.yaml up -d --wait
. .\scripts\enter_dataforge_cloud.ps1
.\.venv\Scripts\python.exe .\scripts\week5_incremental.py source-init
.\.venv\Scripts\python.exe .\scripts\week5_incremental.py seed
~~~

The sequence-based batch command is local/dry-run by default:

~~~powershell
.\scripts\week5_incremental.ps1 batch --max-events 1000
~~~

For an authorized upload, add `--execute`. Save its returned `manifest_uri` and `manifest_generation` and pass those exact values to the Cloud Run Job:

~~~powershell
.\scripts\week5_incremental.ps1 batch --max-events 1000 --execute
.\scripts\week5_run_job.ps1 `
  -ManifestUri '<manifest_uri from upload receipt>' `
  -ManifestGeneration <manifest_generation from upload receipt> `
  -RunMode normal
.\scripts\week5_incremental.ps1 status --limit 100
.\scripts\week5_incremental.ps1 reconcile
~~~

Normal extraction reads strictly after the committed sequence, captures a bounded upper range, and advances the checkpoint only in the publication transaction. For a bounded backfill, specify both `--from-seq` and `--to-seq` and pass `-RunMode backfill`; backfill never moves the normal checkpoint.

## Safe replay and failure recovery

Run the same completed manifest URI and generation again to observe `NO_OP`. For the one-shot rollback test, add `-FailAfterMergeOnce`; after Cloud Run’s one bounded retry succeeds, keep both attempts in the ledger. For a failed prepublication test, add `-FailAt before_publish`; first confirm the checkpoint and Gold snapshot remain unchanged, then rerun the exact same manifest without the injection flag. Do not rebuild a different batch for recovery.

All failure injections are development-only arguments on this finite job. `failure_recovery.md` documents the tested INC-07/08/10 paths and the earlier transient implementation failures.

## Performance benchmark

Run the fixed, synthetic-only 100K-row benchmark only after checking the project and current cost evidence:

~~~powershell
.\scripts\week5_benchmark.ps1 -Execute
~~~

It caps each query at 256 MiB billed, writes two content-addressed Parquet scratch objects under `tmp/week5/benchmark/`, creates only temporary staging tables, checks both targets against the same Decimal source oracle, and removes the exact temporary generations/tables. The current result is in `performance_benchmark.json`.

## Authentication and cost controls

The operator wrapper reads `docs/cloud/target.json`, selects the isolated DataForge gcloud configuration, and keeps a short-lived access token in-process. If that token expires, read `configuration` from `docs/cloud/target.json` and use `gcloud --configuration=$target.configuration auth login --force` for the existing school account in the School Chrome profile; never send passwords, authorization codes, or access tokens in chat or commit them.

The Week-5 additional-use aim is USD 5 and the project’s USD 10 operational target is not a hard cap. Do not enable the Billing API or upgrade billing to inspect charges. See `iam_cost_cleanup.md` for observed usage, pricing assumptions, billing-status limits, and cleanup receipts. Do not start Week 6 Spark or Week 7 orchestration/dbt from this runbook.
