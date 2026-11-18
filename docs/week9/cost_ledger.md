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

## Paid action log

| Date/time +07 | Action / resource | Official price source | Estimated gross cost | Observed usage | Billed amount | Evidence / cleanup |
|---|---|---|---:|---|---:|---|
| 2026-11-18 19:47 +07 | Seven-date weather slice query (read-only; results downloaded locally, no GCS export), job w9_spike_slice_20261118_01 | [BigQuery pricing](https://cloud.google.com/bigquery/pricing): $6.25/TiB on-demand above the 1 TiB/month account free tier; free usage is not assumed | ≈$0.00006 gross at 10 MiB billed; 1 GiB hard query cap upper bound ≈$0.00611 | 8,008 bytes processed / 10,485,760 bytes billed; 21 rows over 7 dates | Unknown; invoice unavailable | Parquet D:\DATA_ENGINEER\_tmp\w9_spikes\data\weather_7date_slice.parquet, SHA-256 ad79df00245dcdd0a909e08093fe70e02c07884e65dce445d2f3dc5f9114e798; no BigQuery/GCS destination write |

Local package downloads and offline dbt parsing are not GCP spend and are not included as cloud actions. They do not establish an actual cloud bill.
