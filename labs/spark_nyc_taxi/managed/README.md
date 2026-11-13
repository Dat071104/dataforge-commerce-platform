# Managed Spark wrapper (Phase 2 preparation only)

This package prepares the C7 single-month Dataproc Serverless path. It does not download TLC data, upload files, call GCP, or submit a batch by default.

## Local oracle

For the authorized January 2024 Yellow Taxi input, first acquire only that month with the repository's existing downloader, then create the independent Python/Decimal oracle:

```powershell
python ./labs/spark_nyc_taxi/download.py --data-dir D:/dataforge-spark/raw --months 1
python ./labs/spark_nyc_taxi/managed/local_oracle.py `
  --data-dir D:/dataforge-spark/raw `
  --output-json D:/dataforge-spark/evidence/oracle-2024-01.json
```

The oracle verifies the existing local source manifest and re-hashes both input files before reading. It streams Parquet record batches into the independent `oracle.py` logic. That oracle retains per-key durations and source fingerprints; measure local memory before using a full month. No download or oracle run occurred in this lane.

First upload the exact Parquet file, official zone lookup, and local oracle JSON to private `gs://…-bronze/tlc_managed/` prefixes with create-only preconditions. Use read-only `gcloud storage objects describe` checks to capture both generations, then run `stage_manifest.py` to make a sanitized manifest without local paths and with both generations; upload that manifest with a create-only precondition. Record both SHA-256 values, generations, and byte counts. Before submit, `submit.ps1 -Submit` re-reads both object generations and compares them with the staged manifest; it does not overwrite or resubmit on mismatch.

## Fixed batch shape and cost guard

`submit.ps1` is plan-only unless `-Submit` is passed. It always runs `preflight.py` first. The guard models 12 DCUs, a 30-minute TTL, at most two total manual attempts, standard shuffle storage, and a caller-supplied upper bound for the measured GCS/network remainder. It refuses submission when that non-compute bound is missing or the gross total is at/above the USD 4.00 stop threshold (80% of the USD 5 C7 cap).

Example plan-only usage after the cost inputs are measured:

```powershell
./labs/spark_nyc_taxi/managed/submit.ps1 `
  -ProjectId dataforge-p7-lab-d0f725 `
  -Region us-central1 `
  -AttemptNumber 1 `
  -ServiceAccount SERVICE_ACCOUNT_FROM_R1 `
  -RuntimeVersion VERIFIED_RUNTIME_VERSION `
  -StagingBucket gs://PRIVATE_STAGING_BUCKET `
  -MainPythonUri gs://PRIVATE_STAGING_BUCKET/managed/job.py `
  -PyFilesUri gs://PRIVATE_STAGING_BUCKET/managed/spark_nyc_taxi.zip `
  -TripUri gs://PRIVATE_BRONZE_BUCKET/tlc_managed/source/yellow_tripdata_2024-01.parquet `
  -ZonesUri gs://PRIVATE_BRONZE_BUCKET/tlc_managed/source/taxi_zone_lookup.csv `
  -SourceManifestUri gs://PRIVATE_BRONZE_BUCKET/tlc_managed/source/source_manifest.json `
  -LocalOracleUri gs://PRIVATE_BRONZE_BUCKET/tlc_managed/source/oracle-2024-01.json `
  -OutputUri gs://PRIVATE_BRONZE_BUCKET/tlc_managed/2024-01/dataforge-w6-tlc-2024-01-a1 `
  -SourceSha256 SHA256_FROM_MANIFEST `
  -ZoneSha256 SHA256_FROM_MANIFEST `
  -SourceGeneration GCS_GENERATION_FROM_INVENTORY `
  -ZoneGeneration GCS_GENERATION_FROM_INVENTORY `
  -MaximumShuffleGiB MEASURED_UPPER_BOUND `
  -OtherServicesUpperBoundUsd MEASURED_GCS_AND_NETWORK_BOUND
```

Replace placeholders only after read-only inventory and official pricing. Use `-Submit` only in the authorized live phase after confirming the remaining C7 budget, attempt count, source SHA/generation, attached service account, region, and TTL. The wrapper has no automatic retry; Spark task/stage retry counts are set to one attempt. A second submission uses `-AttemptNumber 2` and must remain inside the two-attempt and combined-cost caps.

The batch driver reuses the repository's `validate_tlc_schema`, `apply_quality_policy`, and `aggregate_dataframe` functions. It compares the same-file oracle's row counts, money totals, and key/count checksum before writing Parquet under the isolated managed prefix. It uses an error-if-exists output path and does not publish to commerce or Week-5 datasets.
