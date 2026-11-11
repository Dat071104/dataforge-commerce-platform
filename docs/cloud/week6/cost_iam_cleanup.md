# P7.3 / Week 6 — Cloud boundary, cost, and cleanup

**Week-6 managed Spark status:** `CLOUD_SPARK_NOT_AUTHORIZED`; no managed batch was submitted.

This execution used local Docker Spark against public TLC files. It did not run `gcloud`, write to GCS or BigQuery, change IAM or Terraform, create a managed Spark batch, or alter any accepted cloud checkpoint. The optional managed batch is a separate spending decision; this record is not a claim that GCP account usage or billing is zero.

The approved project metadata remains in `docs/cloud/target.json` (`dataforge-p7-lab-d0f725`, `955038620072`, `us-central1`). Week-4 and Week-5 cloud resources and evidence were left untouched. Existing project billing settlement remains subject to its prior acceptance records.

Downloaded TLC files, local Spark output, Delta scratch tables, event logs, and temporary plans are confined to `labs/spark_nyc_taxi/data/`, which is git-ignored. The source Parquet files are retained locally for reproducibility and were not staged. The lab can be removed by the user after reviewing its evidence; cleanup must not target the commerce database volumes or GCP project resources.

## Optional future cloud gate

Before a managed Spark batch, obtain explicit one-off spending authorization, verify the isolated identity and project/region, check current service pricing and batch configuration, bound executor count and lifetime, and document the expected gross cost plus storage, shuffle, and transfer charges. If any guard cannot be satisfied, do not submit. No cost estimate or usage receipt is claimed for a batch that did not run.
