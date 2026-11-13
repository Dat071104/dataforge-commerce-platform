# DataForge

**Data engineering portfolio | Synthetic commerce, cloud batch, Spark, and weather**

DataForge is a local-first learning project that applies data engineering patterns to synthetic Vietnamese order-to-cash data, then explores separate cloud and Spark workloads. It preserves the original commerce facts and their grains; the NYC taxi and weather labs are independent domains.

**Status:** accepted releases run through P7.4.1; P7.5 is the post-Week-7 code and portfolio closure. Its hosted CI and GitHub release state are tracked in the P7.5 checklist and PR history. Week 8 has not started, and this scope adds no cloud schedule or write.

## What is verified

| Workstream | Evidence-backed result | Boundary |
|---|---|---|
| Local commerce · P6.2 | 3,000 synthetic orders, 10 SQL analyses, 40/40 SQL/DAX checks, five financial controls, and a Power BI model with 10 tables, 15 relationships, 3 pages, and 33 visuals. | Fulfilled sales is a proxy, not recognized revenue. Local release evidence is in [v1.0-local](docs/releases/v1.0-local.md). |
| Week 1 shell exercise · P7.5 | Public CSV fetch, logical-row validation, date partition, content hash, deterministic gzip, and provenance manifest; 16 offline fixture tests pass. | The tests use loopback only. P7.5 PR/hosted CI delivery is tracked separately. [Script and usage](scripts/week1/README.md). |
| GCP foundation · Week 4 | 11 sources, 16,259 rows, 11 successful replays, immutable GCS generations, and typed BigQuery staging. | Sources have different grains; this is not one combined row count or business metric. [Acceptance](docs/cloud/week4_acceptance.md). |
| Incremental batch · Week 5 | 10 live scenarios; checkpoint 20; 108 field comparisons with zero oracle mismatches. Full snapshot and incremental MERGE each billed 44,040,192 bytes in the measured 100K-row test. | Synthetic change-journal workload; that benchmark did not show a billed-byte saving. [Final report](docs/cloud/week5/final_report.md). |
| Local Spark · Week 6 | 13,069,067 TLC input rows; 12,686,794 accepted and 382,273 rejected; DataFrame/SQL parity and a separate daily oracle passed. The output contains 308,833 aggregates. | Broadcast reduced shuffle but was 19.8% slower by median than the shuffled baseline. Managed Spark was not run. [Benchmark](docs/cloud/week6/benchmark.md). |
| dbt and orchestration · Week 7 | 10 live failure/recovery drills; 51 dbt tests; 5 order-control rows matched the independent oracle with zero mismatches; current Gold pointer reached version 6. | Uses only the bounded Week 5 orders/payment simulator, not all Week 4 sources. Cost is an estimate, not an invoice. [Week 7 report](docs/cloud/week7/final_report.md). |
| Weather Mini-project 3 · P7.4.1 | One settled date and three locations produced three reconciled rows. One timed Workflows firing and one local-Docker Airflow integration were recorded; an isolated SCD2 proof produced three versions. | The timed schedule and one-off alert were removed. Airflow was not hosted. The prior receipt describes a sensor, but the operator waited for Cloud Run first; P7.5 removed that redundant sensor. [Closure evidence](docs/cloud/week7/closure/). |
| P7.5 closure | The scheduled empty-conf contract, cloud authorization gate, bounded lifecycle, failure classification, and local notification semantics are implemented. The full offline suite has 210 passed and 7 gated skips. | The pinned Airflow Docker suite could not run because Docker was unavailable. Hosted scheduling, live retries, and new notification delivery are not demonstrated or authorized. See [P7.5 closure](docs/cloud/week7/closure/p75_airflow_correctness.md). |

## Architecture

The four workloads share learning goals and some project infrastructure, but they are separate data domains. Solid arrows show data flow; dashed arrows show orchestration. The editable [diagrams.net source](docs/architecture/dataforge_overview.drawio) is available separately.

~~~mermaid
flowchart LR
  subgraph Local["Local commerce · P6.2"]
    A["Synthetic CSV"] --> B["Python validation"]
    B --> C["Immutable Parquet + manifest"]
    C --> D["PostgreSQL raw / audit"]
    D --> E["Kimball marts + SQL"]
    E --> F["Power BI Desktop"]
  end

  subgraph GCP["GCP commerce · Weeks 4–7"]
    W4A["Week 4: 11 source extracts"] --> W4B["Private GCS Bronze"] --> W4C["BigQuery raw + typed staging"]
    W5A["Week 5: local PostgreSQL change journal"] --> W5B["Immutable GCS manifest"] --> W5C["Cloud Run Jobs"] --> W5D["BigQuery Silver + checkpoint"] --> W5E["dbt candidate + tests"] --> W5F["Versioned Gold + pointer"]
    WF["Workflows control plane"] -.-> W5C
    WF -.-> W5E
  end

  subgraph Spark["Separate local Spark lab · Week 6"]
    S1["Official NYC TLC Parquet"] --> S2["Docker + PySpark"]
    S2 --> S3["Quality + hourly/zone aggregates"]
    S3 --> S4["Partitioned Parquet + local Delta"]
  end

  subgraph Weather["Separate Mini-project 3 weather domain"]
    M1["Open-Meteo ERA5"] --> M2["Weather Cloud Run ingest"]
    M2 --> M3["Private GCS raw / typed / manifest"]
    M3 --> M4["BigQuery weather landing"]
    M4 --> M5["Weather dbt Silver + tests"]
    M5 --> M6["Weather-only Gold pointer"]
    M7["Workflows: one timed firing, removed"] -.-> M2
    M8["Airflow 3.4: one local-Docker integration"] -.-> M2
  end
~~~

Week 4's snapshot path and Week 5's change-journal path are distinct exercises. Airflow 3.4 and Workflows are control-plane examples; Cloud Run, GCS, and BigQuery form the weather/commerce data plane. There is no active daily schedule or hosted Airflow service.

The editable diagrams.net XML is included, but this workspace has no diagrams.net/draw.io exporter for an SVG/PNG. The Mermaid block above is the rendered README view; the editable source remains available as a separate file.

## Local quickstart

This starts only the local synthetic commerce demo. It does not need cloud credentials or write to GCP.

~~~powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Set the local database password in .env.
.\scripts\bootstrap_windows.ps1
docker compose up -d --wait
.\scripts\demo_windows.ps1
.\.venv\Scripts\dataforge.exe reference-metrics
~~~

The bootstrap scripts are for Windows. The [local runbook](docs/architecture.md) and [metric contract](docs/metric_contract.md) explain setup, grains, and the reference metrics.

## Engineering decisions

- Keep order items, payments, returns, shipments, and inventory at separate grains; reconcile only through declared keys and independent controls.
- Use content hashes, immutable object generations, stable run identities, and explicit replay behavior to make retries reviewable.
- Build candidate models and tests before publication; expose a versioned Gold result through a guarded pointer.
- Prefer finite, bounded jobs for learning workloads. One successful scheduled firing is evidence for that firing, not a permanent operations service.
- Report measured tradeoffs plainly: the local broadcast join was slower, while the tested incremental BigQuery MERGE billed the same bytes as the comparison snapshot.

## Limits and next work

- Commerce data is synthetic; the Spark lab uses public NYC TLC data and weather uses a bounded Open-Meteo ERA5 slice. Neither lab feeds the commerce facts.
- The GCP-for-Azure/Fabric substitution is recorded as mentor-approved based on the user's report; no separate written approval artifact is in the repository. GCP products are not presented as exact Azure equivalents.
- The Airflow scheduler ran locally for one one-shot integration. Its current code contract is not evidence of an unattended scheduler. A true asynchronous Airflow sensor wait was not demonstrated.
- No recurring failure alert, hosted Airflow, managed Spark job, or settled billing figure is claimed. The one-time alert delivery is retained as historical evidence; no active alert remains.
- The final independent controller, exact-head hosted CI, PR, and merge are tracked in the P7.5 execution checklist and GitHub history; local green tests alone do not establish a release. Certification courses, Week 8+, and mentor sign-off are not claimed as complete.

## Evidence navigation

- [Evidence index](docs/EVIDENCE_INDEX.md) · [Syllabus coverage](docs/SYLLABUS_COVERAGE.md)
- [Architecture decision record](docs/demo/week7_checkpoint/architecture_and_tradeoffs.md) · [Editable architecture](docs/architecture/dataforge_overview.drawio)
- [Week 7 mentor walkthrough](docs/demo/week7_checkpoint/walkthrough.md) · [Technical defense](docs/demo/week7_checkpoint/technical_defense.md) · [Safe demo checklist](docs/demo/week7_checkpoint/demo_acceptance_checklist.md)
- [GitHub hygiene audit](docs/github_hygiene_audit.md) · [Deferred issue drafts](docs/roadmap/deferred_issue_drafts.md) (drafts only; no issues created)
- [P6.2 local release](docs/releases/v1.0-local.md) · [Week 4](docs/cloud/week4_acceptance.md) · [Week 5](docs/cloud/week5/final_report.md) · [Week 6](docs/cloud/week6/final_report.md) · [Week 7](docs/cloud/week7/final_report.md) · [Mini3 closure](docs/cloud/week7/closure/final_report.md)
- [P7.5 Airflow correctness](docs/cloud/week7/closure/p75_airflow_correctness.md) · [Persistent P7.5 checklist](docs/cloud/week7/closure/p75_execution_checklist.md)
