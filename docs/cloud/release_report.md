# P7.1 Week-4 deployment and release report

**Deployment:** 2026-11-09. **Final local checks:** 2026-11-10 (Asia/Bangkok). **Independent review:** CLOUD_GO_WEEK4, release_ready true. **GitHub release:** exact-head hosted CI is required before merge.

The user selected a new isolated project and an operational task target below USD 10 after shared SaigonBite resources were discovered. Existing projects and the accepted P6.2 `v1.0-local` baseline were preserved.

| Resource | Actual identifier / outcome |
|---|---|
| Project / number | `dataforge-p7-lab-d0f725` / `955038620072` |
| Region | `us-central1` for GCS, native BigQuery datasets and jobs |
| Private Bronze | `gs://dataforge-p7-lab-d0f725-bronze` |
| Datasets | `dataforge-p7-lab-d0f725.staging`, `.silver`, `.gold`; Silver/Gold empty |
| Runtime identity | `dataforge-runtime@dataforge-p7-lab-d0f725.iam.gserviceaccount.com`; zero user-managed keys |
| Terraform workspace | `p7-dataforge-p7-lab-d0f725`; 11 applied creates, no changes/deletes; no drift |
| Active synthetic run | `1b8ab9513d624bbcba6692a6ea0818f6` |

All 11 sources and all 11 safe reruns passed: **16,259 rows across separate grains**, 11 raw and 11 typed staging tables, exact schemas/keys/nullable fields/values, reused load and cast jobs, and unchanged GCS Parquet/manifest generations. Source counts are in [the acceptance matrix](week4_acceptance.md); all job IDs and hashes are in [first-pass receipts](evidence/transfers/) and [rerun receipts](evidence/reruns/).

Geography's eight-row first load was `dataforge_load_geography_1b8ab9513d624bbcba6692a6ea0818f6_6e81034d63a7`; typed cast was `dataforge_cast_geography_1b8ab9513d624bbcba6692a6ea0818f6_5dbd5507dcb3`. Its Parquet SHA-256 is `f344ecbda43de5c0b76bdd1917ccc142c0b01746c380ce002ed42fa64a7ff966`, generation `1794241093122561`, CRC32C `YGvg+A==`. The matching manifest SHA-256 is `fb7d14dbb8948f1e1697ac1eb0f0540272d091c51882b6287680d27e04af59ab`, generation `1794241095938778`. Aggregate GCS footprint: **22 objects / 249,795 bytes**, including 235,910 Parquet bytes.

The runtime identity read the object and queried eight rows/eight distinct keys using `dataforge_runtime_verify_geography_8154f1ee3830`. Anonymous object access and runtime Gold listing were denied (403). The operator retains existing Project Owner permission; least privilege is demonstrated for runtime only. Scoped impersonation is retained for Week-5 checks; no service-account key was created.

Measured usage: **89 completed jobs** (11 batch loads, 78 queries), 2,786,762 query bytes processed and **587,202,560 bytes billed**. The query list-price equivalent is USD 0.003338 before credits/free tiers; the conservative executed-task estimate is **below USD 0.02**. Billing is linked and active, but the new project's settled charge has **not yet posted**. USD 10 is an operational target, not a cap. See [cost receipt](cloud_cost_receipt.md) and [job ledger](evidence/usage_summary.json).

Final local validation: **127 passed in 25.95 seconds**, including PostgreSQL integration, exit 0; Ruff, compileall, pip check, PowerShell parse and diff checks passed. Power BI source validation passed (10 tables, 15 relationships, 3 pages, 33 visuals); all five PostgreSQL/Decimal financial controls matched. A Docker-stopped connection failure was resolved before this passing rerun. The publication candidate review found no high-confidence credential/billing-account/personal-email patterns or broken local links; a dedicated secret scanner was unavailable.

Read [the independent verdict](controller_verdict.md) for release readiness. The feature branch is `feature/p7-week4-gcp-foundation`, based on `e5d8dfba6d996c8a68913ce8113b8f6aeeea502b`. Commit/push/PR follow only a successful controller decision; merge follows actual hosted CI on the final PR head. Publication metadata will be recorded here and in the PR.

Week 5 remains separate: create an append-only operational change journal, deterministic insert/update/delete/late cases, watermarks, replay/recovery, bounded BigQuery Silver merges and independent parity checks. Cloud Run is future work; CDC, Spark, dbt, schedules and cloud Gold publication have not run. Mentor acceptance of GCP in lieu of Azure/Fabric remains pending. Retained resources and reviewed cleanup are described in [cleanup.md](cleanup.md).
