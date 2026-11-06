# Data quality and reconciliation report

**Observed:** 2026-11-03 (Asia/Bangkok), seed-42 synthetic fixture, 3,000 orders, PostgreSQL 16.14.

This is dated local verification for the synthetic fixture. Detailed Codex run receipts and raw provider responses are not part of the public package; the current v1.0-local status is summarized in [`docs/releases/v1.0-local.md`](releases/v1.0-local.md).

## Source and Gold row counts

| Source / fact | Rows | Source / fact | Rows |
|---|---:|---|---:|
| Geography | 8 | Customers | 300 |
| Customer segment versions | 342 | Products | 60 |
| Orders | 3,000 | Order items / `dw.fct_order_item` | 6,001 |
| Payments / `dw.fct_payment` | 2,865 | Shipments / `dw.fct_shipment` | 2,564 |
| Returns / `dw.fct_return` | 139 | Inventory / `dw.fct_inventory_snapshot` | 180 |
| Weather / `dw.fct_weather_daily` | 800 | `analytics.vw_order_reconciliation` | 3,000 |

All 11 CSV source snapshots were accepted with zero rejected rows. Each source hash maps to a content-addressed Parquet output and a complete active run. The fresh pipeline and repeated snapshot load/build left raw source counts equal to the active manifest; Gold fact counts remained at source grain. The PostgreSQL integration suite includes repeat-load/idempotency coverage.

## Independent financial reconciliation

The oracle reads the synthetic CSV files and uses Python `Decimal`; the SQL control reads independently built Gold facts/views. Amounts below are VND.

| Metric | CSV `Decimal` oracle | PostgreSQL control | Result |
|---|---:|---:|---|
| Fulfilled sales proxy | 5,030,565,500.00 | 5,030,565,500.00 | Match |
| Fulfilled COGS proxy | 2,946,637,500.00 | 2,946,637,500.00 | Match |
| Collected successful payments | 5,030,565,500.00 | 5,030,565,500.00 | Match |
| Completed refunds | 135,428,000.00 | 135,428,000.00 | Match |
| Collection variance | 0.00 | 0.00 | Match |

The active synthetic source is deliberately constructed to reconcile successful collections to the delivered-sales proxy. Refunds remain a separate return-date event and are not subtracted from the order-date variance. These controls do not establish accounting-recognized revenue. The independent CSV `Decimal` oracle and PostgreSQL controls matched for five monetary metrics; current release verification is summarized in [`docs/releases/v1.0-local.md`](releases/v1.0-local.md).

## Warehouse and quality checks

- The full synthetic `db-check --synthetic` run returned zero for every orphan/reference, SCD2 current/as-of/overlap, fact-grain/cardinality, date coverage, snapshot audit and payment-variance assertion.
- A second `db-load`, `db-build` and `db-check --synthetic` run succeeded. Raw counts still matched all 11 source counts, Gold fact counts remained one row per defined fact grain, and all 33 SQL checks were zero.
- PostgreSQL integration tests include duplicate snapshot keys, bad references, overlapping/invalid SCD2 history, transactional rollback, unchanged-hash no-op behavior and stable dimension keys.
- The isolated weather API smoke returned two rows and produced a Parquet file under a temporary directory; it was not merged into the canonical synthetic database. The raw response and run receipt are not included in this portfolio. See [`docs/source_provenance.md`](source_provenance.md) for provider and attribution boundaries.

## Query execution

All ten analytics SQL files exited successfully against the main 3,000-order Gold marts after the final demo build. The 100K-order benchmark also executed all ten queries in its isolated database; see [`performance_benchmark.md`](performance_benchmark.md). Detailed per-run Codex receipts are intentionally not part of the public package.

## Boundaries

- Commerce and canonical weather values in this report are synthetic. The live weather smoke is a distinct, provider-sourced sample with its own attribution and license terms.
- The IVin Datathon files were not downloaded or profiled because no reuse license or explicit reuse terms were visible in the reviewed repository root/README. No third-party business records are included.
- The order reconciliation view is one row per order and has no customer/product slice path. Do not join raw payment, return, shipment and order-item rows before aggregation.
- This report describes a local portfolio workload, not production volume, financial reporting, a service-level agreement or a general performance guarantee.
