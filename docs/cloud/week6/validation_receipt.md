# P7.3 / Week 6 — local validation receipt

**Worktree:** `feature/p7-week6-spark-nyc-taxi` at pre-release base `839f7a5a2e39f3fec6c071d8a8a04a1c07ea70a4`.
**No GCP operations:** managed Spark batch not authorized; no GCP write or resource/IAM mutation occurred.

## Spark lab CI

Command from the repository root:

```powershell
.\labs\spark_nyc_taxi\ci.ps1
```

**Exit 0.** Pinned Docker image build completed. The network-free fixture suite passed **30 tests in 22.07 seconds**. The suite does not download TLC source data.

Additional local checks:

| Command | Result |
|---|---|
| `.venv\Scripts\ruff.exe check src tests scripts dashboards/P5 labs/spark_nyc_taxi` | Exit 0, `All checks passed!` |
| `.venv\Scripts\python.exe -m compileall -q src tests scripts dashboards/P5 labs/spark_nyc_taxi` | Exit 0 |
| `.venv\Scripts\python.exe -m pip check` | Exit 0, `No broken requirements found` |
| `git diff --check` | Exit 0 |
| `.venv\Scripts\python.exe dashboards/P5/validate_source_pack.py` | PASS: 10 model tables, 15 relationships, 3 pages, 33 visuals; no-secret checks passed. Workbook path remains intentionally unconfigured. |

## Accepted commerce regression

| Command | Result |
|---|---|
| `$env:RUN_POSTGRES_TESTS='0'; .venv\Scripts\python.exe -m pytest -q tests dashboards/P5/tests` | **155 passed, 7 expected DB-gated skips** in 20.17 seconds |
| `$env:RUN_POSTGRES_TESTS='1'; .venv\Scripts\python.exe -m pytest -q -o faulthandler_timeout=60 tests dashboards/P5/tests` | **161 passed, 1 expected skip** (separate Week-5 operational-source database) in 31.50 seconds |

PostgreSQL tests created/dropped unique temporary databases; the accepted `dataforge` database and volume were not truncated or reset. P6.2/P7.1/P7.2 source code, financial metrics, checkpoints and cloud resources have no diff.

## Full Spark run

Finalization command (the 5-run benchmark receipt was recovered from its completed event log after the original wrapper rejected exact equality on approximate-percentile summary totals):

```powershell
.\.venv\Scripts\python.exe -m labs.spark_nyc_taxi.eventlog_report `
  --event-log .\labs\spark_nyc_taxi\data\eventlogs\local-1794323176305 `
  --output-dir .\labs\spark_nyc_taxi\data\output\runs\week6-20261110-02\benchmark `
  --run-id week6-20261110-02 `
  --source-manifest-sha256 08a0436c78c304eae623b34e674aa7a983e7a6e01bf36dd8d81d14c771a2c487 `
  --input-rows 13069067 `
  --spark-version 3.5.9 --shuffle-partitions 96 --warmups 1 --repetitions 5

docker compose --file labs/spark_nyc_taxi/compose.yaml run --rm spark `
  -m labs.spark_nyc_taxi.job `
  --raw-dir /workspace/labs/spark_nyc_taxi/data/raw `
  --output-root /workspace/labs/spark_nyc_taxi/data/output `
  --run-id week6-20261110-03 `
  --warmups 1 --repetitions 5 --shuffle-partitions 96 --output-partitions 16 `
  --reuse-benchmark /workspace/labs/spark_nyc_taxi/data/output/runs/week6-20261110-02/benchmark/benchmark.json
```

| Receipt | Value |
|---|---|
| Finalization run ID | `week6-20261110-03` |
| Spark application ID | `local-1794329076657` |
| Benchmark application ID | `local-1794323176305` |
| Spark source count | 13,069,067; matched four Parquet footer counts |
| Accepted / rejected | 12,686,794 / 382,273 |
| DataFrame / SQL parity | PASS; zero differing rows |
| Independent full-date Oracle | PASS; 77,033 source rows for 2024-01-15 |
| Partitioned Parquet | PASS; 308,833 rows, 121 date partitions/files; same-run replay `VERIFIED_NO_OP` |
| Delta table | PASS; 20 rows v0, append 21 rows v1, replay unchanged, v0 read 20 |
| Managed Spark | `CLOUD_SPARK_NOT_AUTHORIZED`; not run |

The result artifacts are summarized in [output_reconciliation.json](output_reconciliation.json). Raw Parquet, generated output, and event logs remain ignored under `labs/spark_nyc_taxi/data/`.
