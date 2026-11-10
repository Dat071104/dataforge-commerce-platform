# Week-4 budget assumptions and measured outcome

The user's latest instruction replaced the shared-project proposal with a new isolated project, `dataforge-p7-lab-d0f725`, and raised the task's operational target to **below USD 10**. This is not a hard cap, recurring-spend authorization, or billing upgrade.

The frozen fixture has 11 synthetic Parquet files, 235,910 bytes, and 16,259 rows across different grains. Geography has eight rows / 2,378 bytes. Source contents and the local P6.2 baseline were preserved.

## Bounded execution estimate

One first pass per source uses four capped queries and one shared-pool batch load. A completed rerun uses three verification queries and reuses the prior load/cast. Eleven first passes, eleven reruns, and one runtime query make 78 query jobs. At 256 MiB maximum per query, a conservative uncached envelope is 19.5 GiB, approximately USD 0.119 at USD 6.25/TiB. Allowing for current tiny storage/operations, the pre-run envelope was below USD 0.20, before free tiers or credits.

Observed query bytes billed were 587,202,560; their list-price equivalent is **USD 0.003338**. The current executed-task estimate is below USD 0.02. These are usage-derived estimates, not settled charges. The new project's billing-report row has not posted yet. See [the cost receipt](cloud_cost_receipt.md).

## Stop and retention controls

- Stop on a wrong project/owner/location, unexpected permission or service, failed reconciliation, query cap, or projected task spend above USD 10.
- Run sources sequentially, stop on first error, and do not repeat successful loads. Requests/retries have 60-second bounds; job waits have a 300-second bound.
- Keep the private Bronze bucket, three datasets, and keyless runtime account for Week 5. Only staging tables carry a seven-day TTL. Bronze is retained until reviewed cleanup.
- No VM, Cloud SQL, GKE, Composer, Cloud Run Job, Scheduler, managed Spark, or recurring workload is deployed.
- Billing alerts are not spend caps; no automatic cap is claimed. Future weeks require their own reviewed plan and cost envelope.

References: [BigQuery pricing](https://cloud.google.com/bigquery/pricing), [Cloud Storage pricing](https://cloud.google.com/storage/pricing), [BigQuery batch loading](https://docs.cloud.google.com/bigquery/docs/batch-loading-data), and [billing budgets](https://docs.cloud.google.com/billing/docs/how-to/budgets).
