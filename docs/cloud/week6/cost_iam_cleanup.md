# P7.3 / Week 6 — Cloud boundary, cost, and cleanup

**Week-6 managed Spark status:** `CLOUD_SPARK_NOT_AUTHORIZED`; no managed batch was submitted.

This original local execution used Docker Spark against public TLC files; it did not write to GCS or BigQuery or mutate IAM/Terraform. Its original managed-batch status was not authorized. The separate 2026-11-18 S7-R batch is recorded in the addendum below. This record is not a claim that GCP account usage or billing is zero.

The approved project metadata remains in `docs/cloud/target.json` (`dataforge-p7-lab-d0f725`, `955038620072`, `us-central1`). Week-4 and Week-5 cloud resources and evidence were left untouched. Existing project billing settlement remains subject to its prior acceptance records.

Downloaded TLC files, local Spark output, Delta scratch tables, event logs, and temporary plans are confined to `labs/spark_nyc_taxi/data/`, which is git-ignored. The source Parquet files are retained locally for reproducibility and were not staged. The lab can be removed by the user after reviewing its evidence; cleanup must not target the commerce database volumes or GCP project resources.

## Optional future cloud gate

Before a managed Spark batch, obtain explicit one-off spending authorization, verify the isolated identity and project/region, check current service pricing and batch configuration, bound executor count and lifetime, and document the expected gross cost plus storage, shuffle, and transfer charges. If any guard cannot be satisfied, do not submit. No cost estimate or usage receipt is claimed for a batch that did not run.
## Subsequent S7-R managed execution addendum (2026-11-18)

A separate, one-off authorized Dataproc Serverless attempt, dataforge-w6-tlc-2024-01-a4, succeeded. It consumed 5,303,300 milli-DCU-seconds and 434,400 GB-seconds of shuffle; estimated compute plus shuffle was USD 0.095000. GCS/network charges and settled billing remain unavailable. No long-lived cluster remains. Full result and limits are in [S7-R evidence](evidence/c7-s7-a4-result-20261118.md) and [cost calculation](evidence/c7-s7-a4-cost-20261118.log). This addendum does not change the scope statement for the original local execution.
