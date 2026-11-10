# P7.1 Week-4 execution summary

**State:** CLOUD_GO_WEEK4 from the independent final controller; deployment and technical verification complete. GitHub release is gated on hosted CI.

The user superseded the shared-project proposal and chose a new isolated project, `dataforge-p7-lab-d0f725` (number `955038620072`), with an operational target below USD 10. Existing SaigonBite and older-project resources were left untouched. The active target is recorded once in [target.json](target.json).

## What actually ran

1. Created the new project, linked the existing active Free Trial without upgrading it, and enabled only the six requested prerequisite APIs; BigQuery enabled its own dependencies.
2. Created a separate SDK configuration/ADC root and fresh Terraform workspace `p7-dataforge-p7-lab-d0f725`. Reviewed a refreshed plan with 11 creates, no updates/deletes, then applied that exact saved plan successfully.
3. Verified private bucket `dataforge-p7-lab-d0f725-bronze`, three co-located native datasets, scoped runtime IAM, and no user-managed service-account key.
4. Uploaded geography first: eight rows, full Parquet/manifest integrity, explicit raw/typed reconciliation, and a generation-preserving completed rerun.
5. Extended to all eleven sources and one safe rerun each: 16,259 source rows across separate grains; 22 GCS objects and 22 staging tables. All exact-value checks passed.
6. Verified keyless runtime reads/query, anonymous private-object denial, Gold denial for runtime, and Terraform drift exit 0 / no changes.
7. Independently listed actual jobs/objects/tables and matched the receipts. Measured 89 completed jobs; query list-price equivalent USD 0.003338; executed-task estimate below USD 0.02. Settled billing remains not yet posted.

## Engineering changes

The cloud adapter is opt-in and retains create-only GCS semantics, precise DATE/INT64/NUMERIC contracts, independent raw/typed row comparisons, provenance reuse, wrong-project/location rejection, bounded requests/jobs, and per-query byte caps. This continuation fixed isolated ADC discovery, added manifest integrity receipt fields, and explicitly disabled job-level retry when supplying a fixed BigQuery job ID. The session helper reads the current target metadata and avoids Store-Python AppData redirection.

Local financial SQL, dataset files, PostgreSQL volume, PBIP, and accepted `v1.0-local` baseline were preserved. The full PostgreSQL-enabled suite passed 127 tests; cloud-focused checks passed 25 tests; Ruff/compileall/dependency checks and Power BI source validation passed. CI installs the optional cloud client extra to exercise credential-isolation tests without live cloud credentials.

## Remaining boundaries

The single independent final controller returned [CLOUD_GO_WEEK4](controller_verdict.md), permitting commit/push/PR. Hosted CI must pass before merge. Billing reporting is delayed; the usage estimate is not an invoice. Mentor approval for Azure/Fabric substitution is unresolved. Cloud Run, source change journals, incremental CDC/Silver merges, managed Spark, dbt, scheduling, and Gold publication remain later-week work.
