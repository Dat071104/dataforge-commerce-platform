# Week 9 cost ledger

Currency: USD. This ledger tracks gross list-price estimates separately from settled billing. One read-only BigQuery query is logged below; no W9 resource write or API enablement has occurred. No invoice or billing export is available.

## Approved limits

| Scope | Cap | Stop line | Current state |
|---|---:|---:|---|
| AF0 total Week 9 | $3.00 | $2.40 (80%) | Approx. $0.00006 gross list-price query estimate; invoice unavailable; no resource write |
| AF8 Data Lineage | $1.00 | $0.80 (80%) | API is currently disabled; no lineage cost recorded |

## Cumulative preflight

| Component | Current gross estimate / reserve | Source |
|---|---:|---|
| Week 7 phase envelope | $12.89274 | `03_CHECKLIST.md` RESUME_POINT and running cost tracker; estimate, not invoice |
| Week 8 authorized reserve | up to $0.10 | Addendum G / `07_COORDINATION.md`; actual use not confirmed here |
| Week 9 approved reserve | up to $3.00 | Addendum F AF0 |
| Combined maximum reserve | $15.99274 | Below the shared $16 stop line by $0.00726; margin is very small |

Before every paid W9 action, refresh the latest Week 7 estimate, confirm the current W8 reserve from its owner, check current official provider prices, and recompute the combined projection. Stop if the projection reaches $16, if W9 reaches $2.40, or if lineage reaches $0.80. An estimate is not a hard billing cap.

## O1 Terraform plan preflight (2026-11-18; no apply)

- Refreshed `03_CHECKLIST.md`: Week 7 gross phase estimate ≈USD 12.89274; Week 8 reserve remains up to USD 0.10 because actual use is unconfirmed. With the W9 cap USD 3.00, the combined maximum reserve is USD 15.99274, USD 0.00726 below the shared USD 16 stop. At the W9 stop line USD 2.40, the combined projection is USD 15.39274.
- Official BigQuery on-demand price: USD 6.25/TiB above the first 1 TiB/month/account; minimum billable scan is 10 MiB per query. Keep `maximum_bytes_billed=1 GiB` on every W9 query (gross list-price upper bound ≈USD 0.00611/run); do not assume free-tier availability. [BigQuery pricing](https://cloud.google.com/bigquery/pricing)
- Secret Manager management operations, including secret-container creation, are free. For conservative planning, do not assume its monthly free tier: active versions above six are USD 0.000082192 per version-hour, so one active version retained for seven days is ≈USD 0.01381; access operations above 10,000/month are USD 0.03 per 10,000. [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)
- O1 plans were read-only and created no resources or secret versions. The first 24/0/0 plan is stale because retention protections changed; its binary `C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-readonly.tfplan` remains and is marked **DO NOT APPLY** after policy review rejected its deletion (no retry). The final plan after retention/TTL changes is 24 add / 0 change / 0 destroy, reviewed read-only at `C:\Users\ADMIN\AppData\Local\Temp\dataforge-w9-o-final-readonly-plan.txt`; it is an integrator review artifact only and has not been applied. No W9 resource/API write occurred; invoice unavailable. Current W9 gross estimate remains ≈USD 0.00006 from the single read-only query.

## Paid action log

| Date/time +07 | Action / resource | Official price source | Estimated gross cost | Observed usage | Billed amount | Evidence / cleanup |
|---|---|---|---:|---|---:|---|
| 2026-11-18 19:47 +07 | Seven-date weather slice query (read-only; results downloaded locally, no GCS export), job w9_spike_slice_20261118_01 | [BigQuery pricing](https://cloud.google.com/bigquery/pricing): $6.25/TiB on-demand above the 1 TiB/month account free tier; free usage is not assumed | ≈$0.00006 gross at 10 MiB billed; 1 GiB hard query cap upper bound ≈$0.00611 | 8,008 bytes processed / 10,485,760 bytes billed; 21 rows over 7 dates | Unknown; invoice unavailable | Parquet D:\DATA_ENGINEER\_tmp\w9_spikes\data\weather_7date_slice.parquet, SHA-256 ad79df00245dcdd0a909e08093fe70e02c07884e65dce445d2f3dc5f9114e798; no BigQuery/GCS destination write |

Local package downloads and offline dbt parsing are not GCP spend and are not included as cloud actions. They do not establish an actual cloud bill.
