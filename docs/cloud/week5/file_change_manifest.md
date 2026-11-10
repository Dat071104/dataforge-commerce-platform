# Week-5 file change manifest

## Implementation

- `src/dataforge/incremental/`: source journal client, sequence batch contract, Decimal Oracle, immutable Bronze handling, and independent reconciliation.
- `labs/operational_source/`: isolated PostgreSQL schema, Docker Compose, and simulator notes.
- `cloud/jobs/week5/`: finite Cloud Run Job consumer, digest-pinned container build, and pinned runtime dependencies.
- `cloud/sql_bigquery/week5/`: additive Week-5 operational/Silver/Gold schemas, transaction-safe publish script, and SQL contract checks.
- `src/dataforge/cloud/google_cloud.py` and `src/dataforge/cloud/contracts.py`: exact-generation GCS reads/writes, bounded BigQuery staging/publication, retry-safe ledger operations, and response contracts.
- `cloud/terraform/dev/`: additive Week-5 dataset, API, Artifact Registry, IAM, and Cloud Run Job resources.
- `scripts/`: Week-5 source/batch/status/reconcile/job operator, Cloud Run wrapper, and bounded snapshot/MERGE benchmark.
- `tests/incremental/`: source, Decimal Oracle, manifest, runtime, reconciliation, CLI, and benchmark contract checks.

## Evidence and operations

- `docs/cloud/week5/`: ADR/contract/scenario plan, live acceptance matrix, sanitized ledger, exact GCS generations, Cloud Run image/execution receipts, full BigQuery parent/child job inventory, Decimal source snapshot, independent oracle, reconciliation CSV, incident snapshots, benchmark, cost/IAM/cleanup, runbook, final report, controller verdict, and this manifest.
- `README.md`: preserves the accepted P6.2 and P7.1 states, adds the verified Week-5 path and short operator quickstart, and keeps Azure/Fabric mapping separate from assessment claims.

## Preserved boundaries

- P6.2 local artifacts, P7.1 Week-4 cloud artifacts, and prior controller verdicts were not edited.
- No Week-6 Spark or Week-7 orchestration/dbt code or infrastructure was added.
- No `.env`, ADC, service-account key, Terraform state, private billing screenshot, or access token is included in the change set.
