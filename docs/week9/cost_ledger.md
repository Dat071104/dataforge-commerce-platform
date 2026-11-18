# Week 9 cost ledger

Currency: USD. This ledger tracks gross list-price estimates separately from settled billing. One read-only BigQuery query is logged below; no W9 resource write or API enablement has occurred. No invoice or billing export is available.

## Approved limits

| Scope | Cap | Stop line | Current state |
|---|---:|---:|---|
| AF0 total Week 9 | $3.00 | $2.40 (80%) | Approx. $0.00006 gross list-price query estimate; O1 control-plane resources applied; no data rows or secret versions; incremental C10 state storage not separately measured; invoice unavailable |
| AF8 Data Lineage | $1.00 | $0.80 (80%) | API is currently disabled; no lineage cost recorded |

## Cumulative preflight

| Component | Current gross estimate / reserve | Source |
|---|---:|---|
| Week 7 phase envelope | $12.89274 | `03_CHECKLIST.md` RESUME_POINT and running cost tracker; estimate, not invoice |
| Week 8 authorized reserve | up to $0.10 | Addendum G / `07_COORDINATION.md`; actual use not confirmed here |
| Week 9 approved reserve | up to $3.00 | Addendum F AF0 |
| Combined maximum reserve | $15.99274 | Below the shared $16 stop line by $0.00726; margin is very small |

Before every paid W9 action, refresh the latest Week 7 estimate, confirm the current W8 reserve from its owner, check current official provider prices, and recompute the combined projection. Stop if the projection reaches $16, if W9 reaches $2.40, or if lineage reaches $0.80. An estimate is not a hard billing cap.

## O1 Terraform plan preflight and I-1 execution (2026-11-18)

- Refreshed `03_CHECKLIST.md`: Week 7 gross phase estimate ≈USD 12.89274; Week 8 reserve remains up to USD 0.10 because actual use is unconfirmed. With the W9 cap USD 3.00, the combined maximum reserve is USD 15.99274, USD 0.00726 below the shared USD 16 stop. At the W9 stop line USD 2.40, the combined projection is USD 15.39274.
- Official BigQuery on-demand price: USD 6.25/TiB above the first 1 TiB/month/account; minimum billable scan is 10 MiB per query. Keep `maximum_bytes_billed=1 GiB` on every W9 query (gross list-price upper bound ≈USD 0.00611/run); do not assume free-tier availability. [BigQuery pricing](https://cloud.google.com/bigquery/pricing)
- Secret Manager management operations, including secret-container creation, are free. For conservative planning, do not assume its monthly free tier: active versions above six are USD 0.000082192 per version-hour, so one active version retained for seven days is ≈USD 0.01381; access operations above 10,000/month are USD 0.03 per 10,000. [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)
- O1 final plan was 24 add / 0 change / 0 destroy. Its first apply created 23 resources; the provider failed because its display name exceeded 32 characters. The display name was shortened, a fresh plan contained 1 add / 0 change / 0 destroy, and the provider-only apply succeeded. Terraform state now has all 24 planned resources. No API enable, BigQuery data/query write, or secret version creation occurred. The original 24/0/0 plan binary `C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-final-readonly.tfplan` is **STALE — DO NOT APPLY** after the partial apply. The pre-retention binary `C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-readonly.tfplan` is also **STALE — DO NOT APPLY**; deletion was rejected by automatic policy review and not retried. The provider-only plan was applied at 2026-11-18 22:53 +07 from `C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-provider-retry-20261118.tfplan`; its text is `dataforge-w9-o-provider-retry-20261118-plan.txt`. A separate offline profile copy under `D:\DATA_ENGINEER\_tmp\w9_q_dbt_profile_20261118` contains no credentials and remains after cleanup was rejected; no retry. Invoice unavailable. The Terraform state object is stored under C10; its incremental size is not separately measured.

## Paid action log

| Date/time +07 | Action / resource | Official price source | Estimated gross cost | Observed usage | Billed amount | Evidence / cleanup |
|---|---|---|---:|---|---:|---|
| 2026-11-18 19:47 +07 | Seven-date weather slice query (read-only; results downloaded locally, no GCS export), job w9_spike_slice_20261118_01 | [BigQuery pricing](https://cloud.google.com/bigquery/pricing): $6.25/TiB on-demand above the 1 TiB/month account free tier; free usage is not assumed | ≈$0.00006 gross at 10 MiB billed; 1 GiB hard query cap upper bound ≈$0.00611 | 8,008 bytes processed / 10,485,760 bytes billed; 21 rows over 7 dates | Unknown; invoice unavailable | Parquet D:\DATA_ENGINEER\_tmp\w9_spikes\data\weather_7date_slice.parquet, SHA-256 ad79df00245dcdd0a909e08093fe70e02c07884e65dce445d2f3dc5f9114e798; no BigQuery/GCS destination write |
| 2026-11-18 22:37 +07 | I-1 O1 partial Terraform apply from the reviewed 24/0/0 plan | BigQuery datasets contained no data; [Secret Manager management operations](https://cloud.google.com/secret-manager/pricing) are free; no active secret version was created. Cloud Audit log query/analysis has no additional charge per [Cloud Logging pricing](https://cloud.google.com/products/observability/pricing). | ≈$0 direct service usage; incremental C10 state-object storage is not separately measured | 23 of 24 planned resources created; provider creation failed with status 3 due display name >32 characters | Invoice unavailable | Terraform state confirmed the provider missing; no BigQuery query/data write, secret version, or API enable. Root cause and correction are in [`terraform-i1-wif-provider-rca-20261118.md`](evidence/terraform-i1-wif-provider-rca-20261118.md); the provider-only retry succeeded in the next row. |
| 2026-11-18 22:53 +07 | I-1 provider-only Terraform apply (`github-oidc`) from fresh 1/0/0 plan | No BigQuery query/data, no secret version; IAM/WIF and Secret Manager management operations have no direct usage charge. Logging query/analysis has no additional charge. | ≈$0 direct service usage; state-object storage remains under C10 and is not separately measured | 1 provider created; Terraform state now has 24/24 planned resources; no API enable | Invoice unavailable | Read-only provider listing returned `projects/955038620072/locations/global/workloadIdentityPools/github-dataforge/providers/github-oidc`; no BigQuery data or secret version. WIF workflow positive/negative tests remain pending GitHub access. |

Local package downloads and offline dbt parsing are not GCP spend and are not included as cloud actions. They do not establish an actual cloud bill.
