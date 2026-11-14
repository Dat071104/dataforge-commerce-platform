# DataForge

**Local commerce, bounded cloud work, a small weather pipeline, and local Spark.**

DataForge demonstrates ingestion, validation, modeling, publication, and recovery across separate learning workloads. Commerce data is synthetic. This is a portfolio, not a production service.

## Portfolio map

~~~mermaid
flowchart LR
  subgraph Commerce["Local commerce"]
    A["Synthetic CSV"] --> B["Python validation"] --> C["Parquet + manifest"] --> D["PostgreSQL + SQL marts"] --> E["Power BI"]
  end
  subgraph Cloud["Bounded cloud commerce"]
    F["Synthetic extracts"] --> G["Private GCS"] --> H["BigQuery"] --> I["dbt models"] --> J["Versioned Gold"]
  end
  subgraph Weather["Weather"]
    K["Open-Meteo ERA5"] --> L["Cloud Run"] --> M["GCS + BigQuery"] --> N["Weather Gold"]
  end
  subgraph Taxi["Local taxi lab"]
    O["NYC TLC Parquet"] --> P["Docker + PySpark"] --> Q["Quality report + Parquet"]
  end
~~~

These workloads share learning goals, not a data model. Weather and taxi data do not feed commerce facts.

## Evidence at a glance

| Workload | Result | Limit |
|---|---|---|
| Local commerce | 3,000 synthetic orders, 10 SQL analyses, 40/40 SQL and DAX checks. [Release](docs/releases/v1.0-local.md) | Fulfilled sales is a proxy, not accounting revenue. |
| Cloud commerce | Bounded transfer and recovery scenarios, dbt tests, guarded Gold publication. [Week 7 report](docs/cloud/week7/final_report.md) | Uses a small synthetic simulator; cost figures are estimates. |
| Weather | One settled date, three locations, three rows; historical Workflow and local Airflow runs. [Receipts](docs/cloud/week7/closure/) | No hosted Airflow, daily schedule, or active alert. |
| NYC taxi | 13.07 million rows processed locally; broadcast was 19.8% slower by median. [Benchmark](docs/cloud/week6/benchmark.md) | Managed Spark was not run. |

## Run the local reference

Docker Desktop and the Windows scripts run the synthetic commerce demo. They need no cloud credentials and do not write to GCP.

~~~powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Set the local database password in .env.
.\scripts\bootstrap_windows.ps1
docker compose up -d --wait
.\scripts\demo_windows.ps1
.\.venv\Scripts\dataforge.exe reference-metrics
~~~

See the [runbook](docs/architecture.md) and [metric contract](docs/metric_contract.md) for setup and grains.

## AI assistance and verification

AI tools assisted with code and documentation. The first-person [engineering decisions](docs/ENGINEERING_DECISIONS.md) are an AI-assisted draft marked AUTHOR REVIEW REQUIRED. The [evidence index](docs/EVIDENCE_INDEX.md) and [syllabus coverage](docs/SYLLABUS_COVERAGE.md) distinguish source, local checks, exact-head CI, historical cloud receipts, and human evidence. Check linked runs for the exact head; tests do not prove a live service.

## Boundaries

Commerce data is synthetic. Current GCP inventory and settled spend are unverified. No hosted Airflow schedule or managed Spark batch is claimed. Work beyond Week 7 is out of scope.