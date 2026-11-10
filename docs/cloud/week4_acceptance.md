# P7.1 Week-4 acceptance matrix

**Current state:** live technical evidence complete; the single independent final controller returned **[CLOUD_GO_WEEK4](controller_verdict.md)** with `release_ready: true` for commit/push/PR.

**Target:** `dataforge-p7-lab-d0f725`, `us-central1`. User selected a new isolated project and a USD 10 operational target after discovery of shared SaigonBite resources.

| Requirement | Result | Evidence |
|---|---|---|
| Local GO baseline and financial grains preserved | PASS | 127 tests including PostgreSQL; unchanged five-control Decimal oracle; Power BI source validation |
| Project, billing, identity, API/location boundary | PASS | `target.json`; isolated SDK helper; live foundation receipt |
| Reviewed Terraform apply | PASS | 11 added / 0 changed / 0 destroyed; plan SHA in reviewed_plan_summary.json; apply exit 0 |
| Private GCS and immutable manifests | PASS | 22 objects; full-byte hashes, CRC32C, generation and owner/location checks |
| Native raw and explicit typed staging | PASS | 11 raw + 11 typed tables; exact schemas, rows, values, nullable fields, keys/digests |
| Geography first smoke | PASS | Eight rows; load/cast/verification job IDs in geography_transfer.json |
| Completed reruns | PASS | 11/11 preserve object generations and reuse load/cast; row counts unchanged |
| Runtime positive and unauthorized negative checks | PASS | Runtime read/query succeeds; anonymous GCS and runtime Gold listing return 403 |
| Actual IAM and drift | PASS | Restricted runtime roles; no user-managed key; Terraform detailed exit 0 / no changes |
| Cloud usage/cost checked | PASS for units and bounded estimate | 89 completed jobs; 587,202,560 query bytes billed; USD 0.003338 query list-price equivalent; total estimate below USD 0.02 |
| Settled bill | NOT YET POSTED | New project absent from the current billing-report rows; no USD 0 settlement claim |
| Week-5 retention | PASS | One private bucket, three datasets, keyless account and scoped IAM; staging TTL seven days |
| Independent final review | CLOUD_GO_WEEK4 | One final controller reviewed all four completed reports, 14 implementation hashes and 11 receipt pairs; no critical/major finding |
| GitHub release | [PR #1](https://github.com/Dat071104/dataforge-commerce-platform/pull/1) | Controller passed; exact-head hosted CI is required before merge; see release_report.md and PR checks |
| Azure/Fabric mentor checkpoint | PENDING / separate | GCP implementation does not automatically satisfy an Azure-specific assessment |

## All-source verification

| Source | Rows | First pass | Safe rerun |
|---|---:|---|---|
| customer_segments | 342 | PASS | PASS |
| customers | 300 | PASS | PASS |
| geography | 8 | PASS | PASS |
| inventory | 180 | PASS | PASS |
| order_items | 6,001 | PASS | PASS |
| orders | 3,000 | PASS | PASS |
| payments | 2,865 | PASS | PASS |
| products | 60 | PASS | PASS |
| returns | 139 | PASS | PASS |
| shipments | 2,564 | PASS | PASS |
| weather_daily | 800 | PASS | PASS |

Counts across sources combine different grains and are not a business KPI. [Usage/job ledger](evidence/usage_summary.json), [resource inventory](evidence/final_resource_inventory.json), [cost receipt](cloud_cost_receipt.md), and [IAM checks](evidence/iam_live_verification.json) supply the underlying evidence.
