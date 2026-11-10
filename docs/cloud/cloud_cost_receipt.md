# Week-4 cloud usage and cost receipt

**Project:** `dataforge-p7-lab-d0f725`. **Checked:** 2026-11-09. **User-approved operational target:** below USD 10 for this task, not a hard cap.

| Observed unit | Result |
|---|---:|
| Sources and completed reruns | 11 + 11 |
| Source rows, across separate grains | 16,259 |
| GCS Parquet / total object bytes | 235,910 / 249,795 |
| GCS immutable objects | 22 (11 Parquet, 11 manifests) |
| BigQuery raw / typed tables | 11 / 11 |
| BigQuery current logical table bytes | 1,750,425 |
| Completed unique jobs | 89 (11 batch loads, 78 queries) |
| Query bytes processed / billed | 2,786,762 / 587,202,560 |
| Query list-price estimate, before free tiers/credits | USD 0.003338 |

The query estimate is measured billed bytes × USD 6.25/TiB; it is not an invoice or a statement of credit consumption. Repeated verification queries may use BigQuery's result cache. Individual jobs, measured bytes, and exact receipts are in [usage_summary.json](evidence/usage_summary.json), [transfers](evidence/transfers), and [reruns](evidence/reruns). A separate job-list read confirmed every recorded job completed without errors.

The executed task is conservatively estimated below **USD 0.02**, including the tiny GCS storage/request footprint and current BigQuery storage, before free tiers/credits. Standard batch loading uses the shared slot pool. The retained storage is inexpensive, but its future cost is not zero or capped. No compute runtime or recurring paid job was deployed.

## Billing observation and limit

Billing is linked and enabled on the new project. The existing Free Trial was visibly active with positive remaining eligibility before deployment; its personal balance and billing-account identifiers are not published.

After the smoke, the Console current-month report grouped by project did **not yet list this newly created project**. Therefore the settled project charge is **NOT YET POSTED / UNKNOWN**, rather than USD 0. Account-level charges from the separate SaigonBite project are excluded from DataForge attribution. Check the project-specific report after billing data arrives; there is no need to repeat the cloud smoke to obtain an invoice.

Each query has a 256 MiB maximum; API retries/requests and job waits are bounded. Staging expires after seven days; only GCS `tmp/` has a 30-day delete rule. No budget alert or automatic spending cap was configured. [Budget assumptions](budget_assumptions.md) and [cleanup](cleanup.md) explain retained resources.

Pricing verified against [BigQuery pricing](https://cloud.google.com/bigquery/pricing), [Cloud Storage pricing](https://cloud.google.com/storage/pricing), and the [Google Cloud Free Program](https://docs.cloud.google.com/free/docs/free-cloud-features). Free tiers are shared by billing account and are not assumed in the estimate.
