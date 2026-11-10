# P7.1 requirement traceability

| Requirement | Owning implementation/evidence | Status |
|---|---|---|
| Preserve local baseline and financial grains | release record; 127-test full suite; unchanged Decimal oracle | PASS |
| Isolated target/auth/state | target.json; session helper; reviewed_plan_summary.json | PASS |
| Private GCS, native datasets, workload identity | Terraform source; live_foundation_inventory.json | CLOUD_TESTED |
| Owner/location verification and create-only uploads | adapters.py; all transfer/rerun receipts | CLOUD_TESTED |
| Parquet and manifest SHA/CRC/generation integrity | 22-object final inventory; transfer receipts | CLOUD_TESTED |
| Exact raw and typed schemas, values, nullable fields, keys | contracts.py; google_cloud.py; eleven reconciled sources | CLOUD_TESTED |
| Completed idempotent reruns | eleven rerun receipts; preserved generations/original load and cast IDs | CLOUD_TESTED |
| Failure/negative coverage | 25 cloud tests; anonymous GCS 403; runtime Gold 403 | LOCAL_AND_CLOUD_TESTED |
| Restricted runtime, no static key | live IAM receipt; zero user-managed keys | CLOUD_TESTED |
| Refreshed Terraform/drift | fmt/init/validate/plan/apply; drift exit 0 | CLOUD_TESTED |
| Usage/cost and retained resources | usage_summary.json; cloud_cost_receipt.md; cleanup.md | Measured units; settlement not posted |
| README and Azure/Fabric mapping | README.md; syllabus_mapping.md | Functional mapping; mentor pending |
| Independent controller and GitHub release | controller_verdict.md; release_report.md | CLOUD_GO_WEEK4; hosted CI next |
| Cloud Run/CDC/Spark/dbt/scheduling | No Week-4 runtime deployed | DEFERRED |
