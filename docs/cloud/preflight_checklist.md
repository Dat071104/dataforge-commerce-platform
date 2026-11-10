# P7.1 current preflight checklist

The earlier shared-project/authentication blockers are historical. The user selected a new isolated project and authorized its Week-4 deployment with a USD 10 operational target.

| Gate | Status | Evidence |
|---|---|---|
| Preserve P6.2 baseline | PASS | Baseline `e5d8dfb`; feature branch; original local SQL/PBIP/data preserved |
| Remote baseline and CI | PASS | Remote main matched baseline; Actions run 42198663488 / #6 succeeded before this change |
| School CLI/ADC, project, billing | PASS | New project `dataforge-p7-lab-d0f725` ACTIVE; billing linked/enabled; isolated SDK/ADC selected by `target.json` and session helper |
| Dedicated state | PASS | Fresh `p7-dataforge-p7-lab-d0f725`; 11-create plan applied; no prior state imported |
| APIs and region | PASS | Six requested prerequisite APIs; BigQuery dependencies auto-enabled; bucket and all datasets are in `us-central1` |
| Private IAM/runtime | PASS | [Live foundation](evidence/live_foundation_inventory.json); [positive/negative IAM](evidence/iam_live_verification.json) |
| Validated synthetic inputs | PASS | All 11 sources reconciled exactly after upload; raw and typed checks pass |
| Geography first smoke and rerun | PASS | Eight rows; hashes/generations retained; original load/cast reused |
| All-source first pass and rerun | PASS | 11 + 11 receipts; 16,259 mixed-grain rows; no duplicate output |
| Terraform drift | PASS | [Detailed exit 0 / no changes](evidence/terraform_drift.json) |
| Usage/cost controls | PASS; settlement pending | [Measured usage and estimates](cloud_cost_receipt.md); billing report has not yet posted the new project |
| Mentor accepts GCP substitution | PENDING | No Azure/Fabric equivalence or syllabus acceptance claimed |
| Independent controller / release | CLOUD_GO_WEEK4 / CI NEXT | Final controller passed; hosted CI must precede merge |

The two previous projects are excluded from active DataForge configuration. Their resources were not changed. Historical read-only inventories remain in `evidence/`. No later-week runtime is deployed.
