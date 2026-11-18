# Week 9 cost ledger

Currency: USD. This ledger tracks gross list-price estimates separately from settled billing. No W9 paid cloud action has been run as of 2026-11-18; no invoice or billing export is available.

## Approved limits

| Scope | Cap | Stop line | Current state |
|---|---:|---:|---|
| AF0 total Week 9 | $3.00 | $2.40 (80%) | $0.00 W9 cloud action recorded |
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
| — | No paid W9 cloud actions yet | — | $0.00 | — | Unknown | No W9 GCP write or lineage API enable recorded |

Local package downloads and offline dbt parsing are not GCP spend and are not included as cloud actions. They do not establish an actual cloud bill.
