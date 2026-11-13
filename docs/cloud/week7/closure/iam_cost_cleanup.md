# P7.4.1 IAM, cost, and cleanup review

**Review date:** 2026-11-13.
**Project:** dataforge-p7-lab-d0f725 / 955038620072, us-central1.
**Scope:** additive Mini3 resources and the one-off scheduler/notification proof. No accepted commerce resource was changed.

## Identity and infrastructure review

The isolated ADC profile resolved to the approved project. Its Resource Manager read returned ACTIVE and the expected project number; the final refreshed Terraform plan also completed through ADC. On 2026-11-13 the separate gcloud CLI credential could not refresh non-interactively and asked for a new `gcloud auth login`; this was not an IAM 403 and did not prevent the ADC-backed read-only plan. The School account is not treated as a billing-account administrator.

The final refreshed Terraform plan, using the deployed weather image digests and disabled temporary scheduler/notification flags, reported: “No changes. Your infrastructure matches the configuration.” No accepted Week 4/5/7 resource was planned for update, replacement, or destruction.

| Identity | Intended access | Boundary |
|---|---|---|
| dataforge-week7-weather-ingest | Create/read objects below the Mini3 Bronze prefix; create BigQuery jobs; merge only the weather landing table. | No GCS listing, dataset creation, Gold write, or commerce access. |
| dataforge-week7-weather-dbt | Read weather landing; build isolated incremental and full-refresh candidates; update weather Gold versions/pointer; write and clean isolated proof datasets. | No Week 5/order/payment Gold access or Cloud Run invocation. |
| dataforge-week7-weather-wf | Invoke only the two weather Cloud Run Jobs; read exact weather objects and Gold relations; write the Mini3 execution ledger and workflow logs. | No commerce job/table access or public object access. |
| dataforge-week7-airflow | Invoke the same bounded weather jobs and read Gold; check whether the named Scheduler job is paused or absent. | No commerce access, Workflow edits, object writes, or notification configuration. |
| Temporary Scheduler caller | Create Workflow executions only. | Its one-permission project role and caller identity were removed after the automatic run. |

No static service-account key was created. The Airflow runner mounted one isolated keyless ADC file read-only. The temporary School-user Token Creator grant on the Airflow service account was removed after the DagRun. The Cloud Run jobs use one task each with 1 vCPU and 1 GiB limits.

Workflows exposes executions.create only at project scope for this API; IAM Conditions do not provide a per-Workflow resource attribute for this permission. During the single Scheduler proof, a dedicated custom role containing only workflows.executions.create was attached to the temporary Scheduler service account at project scope. The job, service account, custom role, member binding, and act-as grant were removed after its one firing. This is a documented GCP limitation, not a target-level IAM claim. References: [Workflows IAM](https://docs.cloud.google.com/workflows/docs/access-control) and [IAM Conditions resource support](https://docs.cloud.google.com/iam/docs/conditions-resource-attributes).

## Resource state after cleanup

- Retained: Mini3 Workflows definition, two finite Cloud Run Jobs, isolated BigQuery weather datasets, the versioned Gold and ledger, immutable Bronze objects, final digest-pinned images, and SCD2 proof tables with seven-day expiration.
- Removed: the temporary Cloud Scheduler job and its caller permissions, the one-off email channel, the failure-only alert policy, and the temporary user-to-Airflow-service-account impersonation grant.
- Current inventory: zero Cloud Scheduler jobs, zero Monitoring notification channels, zero alert policies. Airflow is not running in GCP.
- The Monitoring API remains enabled because the Terraform service resource uses disable_on_destroy = false. Enabling the API itself does not create a running compute resource.

The weather Bronze prefix occupies 85,162 bytes. Six inspected weather/proof datasets contain eight non-view BigQuery tables totaling 26,483 bytes. The two live Cloud Run jobs currently reference ingest digest sha256:eb63edcaa00ef70a2d52ee880195fba0293674aa96c6ac99c443a092d62f9cbd and dbt digest sha256:6fe1f06a5d3b860fe9013cbc995ba3ad6fdb5ac3821049f5b2dcb19c90e3dc39.

The weather image packages contain 21 retained digests. An authenticated read of their OCI manifests found 283.04 MiB of unique compressed config/layer blobs across those versions; the two currently deployed images account for 282.77 MiB because the builds share almost all base and dependency layers. The historical digests were retained for execution reproducibility. Artifact Registry includes 0.5 GiB-month free per billing account; if that allowance is exhausted, the weather images alone are approximately USD 0.028 per month at current storage rates. Other projects/repositories can use the same billing-account allowance.

## Observed usage and estimated gross cost

The usage snapshot covers work through the final live negative probes on 2026-11-12. It is not a Cloud Billing export.

| Service | Observed usage | Gross list-rate estimate |
|---|---:|---:|
| Cloud Run Jobs | 48 completed one-task executions: 25 ingest and 23 dbt. Observed task wall time totaled 3,968 seconds; estimated billable time was 4,121 seconds after the one-minute minimum for short tasks. | About USD 0.082 at USD 0.000018 per vCPU-second plus USD 0.000002 per GiB-second, for 1 vCPU/1 GiB. This is before any billing-account free tier. |
| BigQuery on-demand | 667 weather-service query jobs in the project job listing; 20 were unsuccessful. Successful work recorded 2,149,580,800 billed bytes (about 2.00 GiB) and 353,870 processed bytes. | About USD 0.0122 at USD 6.25/TiB before account-level free usage. Failed queries are not charged under the published pricing rules. |
| Workflows | 10 Mini3 executions with 747 listed step entries across success and failure runs. The Workflow calls Google APIs and Cloud Run; no direct external HTTP step was used. | Project usage is below the 5,000 monthly internal-step free allowance. Account-level use in other projects is unknown. |
| Cloud Scheduler | One temporary job, one automatic time-based firing, deleted after completion. | At most about USD 0.003 for one billable job-day if the billing account's three free jobs were already used. No recurring Scheduler charge remains. |
| GCS and BigQuery storage | 85,162 bytes under the weather Bronze prefix and 26,483 bytes across the eight measured non-view tables. | Very small incremental storage; account-level free usage is not known. |
| Artifact Registry | 283.04 MiB of unique compressed weather image blobs across 21 digests; two digests are used by the current jobs. | Approximately USD 0.028/month if the account-level 0.5 GiB free allowance is exhausted; the weather images alone remain below that allowance. |
| Monitoring | One temporary email channel and one failure policy, both deleted after the user confirmed the one alert. | No recurring channel or policy remains. Actual billing-account export was unavailable. |

The measured Cloud Run and BigQuery compute subtotal is approximately USD 0.095 before free usage. This excludes any unmeasured network, API operation, logging, Monitoring, Workflow, and cross-project effects. It is below the USD 5 gross demonstration target; it is not a hard cap or a settled bill.

The project billing dashboard was not used as a final charge source. A pre-run view showed VND 0 for an earlier period, which cannot establish the charge for this workload. Actual billed totals and account-wide free-tier consumption remain unknown.

Current official rates and free-tier boundaries are documented by Google: [Cloud Run pricing](https://cloud.google.com/run/pricing), [BigQuery pricing](https://cloud.google.com/bigquery/pricing), [Cloud Scheduler pricing](https://cloud.google.com/scheduler/pricing), [Workflows pricing](https://cloud.google.com/workflows/pricing), [Artifact Registry pricing](https://cloud.google.com/artifact-registry/pricing), and [Cloud Storage pricing](https://cloud.google.com/storage/pricing). Free tiers and pricing aggregation apply at the billing-account level, so they are not claimed as guaranteed savings.
