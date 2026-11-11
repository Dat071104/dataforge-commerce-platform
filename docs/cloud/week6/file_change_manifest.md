# P7.3 / Week 6 — reviewed change manifest

## Added lab code

- `labs/spark_nyc_taxi/download.py`, `oracle.py`, and `quality.py` — official source acquisition/provenance, independent bounded Decimal/DST oracle, quality rules, null/negative/duplicate diagnostics, and accepted/rejected ledger.
- `labs/spark_nyc_taxi/transforms.py`, `job.py`, `spark_session.py`, `benchmark.py`, `eventlog_report.py`, and `table_format.py` — DataFrame/SQL aggregates, reproducible Spark job, schema-safe staged Parquet publication, event-log benchmark, event-log receipt recovery, and isolated Delta operations.
- `labs/spark_nyc_taxi/Dockerfile`, `compose.yaml`, and `ci.ps1` — pinned local Python/Java/Spark/Delta/PyArrow/pytest runtime, 4 CPU / 6 GiB limit, and fixture-only local CI.
- `labs/spark_nyc_taxi/tests/` — network-free source/oracle, quality/transform, job publication, and event-log benchmark contract tests.

## Added or updated documentation

- `docs/cloud/week6/` — architecture/ADR, dataset receipts and quality profile, runtime matrix, benchmark and JSON receipt, Spark UI/event log evidence, physical plans, Parquet pruning plan, output reconciliation, Delta operations, acceptance matrix, local validation receipt, independent controller verdict, cost/cloud boundary, final report, and this manifest.
- `labs/spark_nyc_taxi/README.md` — local setup, execution, fixture CI, data contract, and evidence links.
- `README.md` — concise Week-6 status, separate Spark architecture arrow, and links.
- `docs/cloud/syllabus_mapping.md` — local Spark status updated while managed Spark and Azure/Fabric equivalence remain unclaimed.
- `docs/releases/v1.0-local.md` — additive Week-6 follow-on record; the P6.2 acceptance evidence remains unchanged.

## Updated ignore and CI boundaries

- `.gitignore` excludes `/labs/spark_nyc_taxi/data/`; raw TLC data, source manifests, output Parquet/Delta tables, event logs, and scratch receipts remain local only.
- `.github/workflows/week6-spark.yml` builds the pinned image and runs deterministic fixture tests. It never downloads TLC source data or submits cloud work.

## Explicitly untouched

No source, SQL, or tests under the accepted commerce pipeline were changed. Commerce fact grains, metrics, Silver/Gold models, cloud checkpoints, Week-4/5 resources, accepted P6.2/P7.1/P7.2 controller verdicts, Terraform state, GCP IAM, and cloud data were untouched. No Week-7 dbt/orchestration work was started. Managed Spark was not run or charged by this phase.

Generated scratch outputs and the two non-final benchmark harness attempts remain under the ignored local `data/` tree; only compact source hashes, task metrics, plans, and reconciliations are included in the review diff.
