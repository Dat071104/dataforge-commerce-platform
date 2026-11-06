# Windows local runbook

## 1. First setup

From PowerShell, run commands from the cloned repository root:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Set a unique local-only POSTGRES_PASSWORD in .env; keep the file private.
.\scripts\bootstrap_windows.ps1
docker compose up -d --wait
```

Bootstrap creates a Python 3.11 venv and installs `.[dev,powerbi]` under the resolved `requirements-py311.lock` constraints. The `powerbi` extra supplies `openpyxl` for workbook snapshot generation. Core ingestion and warehouse commands do not depend on it. Compose binds to loopback at `127.0.0.1:5433`.

## 2. Rebuild the deterministic synthetic demo

```powershell
.\.venv\Scripts\dataforge.exe generate --orders 3000 --seed 42
.\.venv\Scripts\dataforge.exe ingest
.\.venv\Scripts\dataforge.exe db-init
.\.venv\Scripts\dataforge.exe db-load
.\.venv\Scripts\dataforge.exe db-build
.\.venv\Scripts\dataforge.exe db-check --synthetic
.\.venv\Scripts\dataforge.exe reference-metrics
```

The generator writes the deterministic fixture only when the source folder is empty or its provenance marker says `synthetic` and every existing CSV matches its recorded SHA-256. It refuses manual, externally sourced or edited CSVs before writing. It does not drop the local database. Ingestion validates each complete CSV snapshot and writes content-addressed Parquet with an actual-byte SHA-256, schema and row-count record. Raw snapshot loading and Gold mart building are separate transactions.

The one-command `scripts/demo_windows.ps1` runs seed-42 generation, ingestion, database initialization/load/build, all synthetic checks, the five-value CSV `Decimal`-to-PostgreSQL control comparison, all ten SQL analyses, then repeats ingestion/load/build and rechecks results. It is safe to rerun on an intact synthetic source folder; it does update the configured local database. Use an isolated PostgreSQL database when testing failures or recovery.

### Safe synthetic reset after external/manual data

Do not run `generate` over API-derived or user-supplied source files. Preserve the current folder under a unique archive name, then create a fresh empty default source directory:

```powershell
$archive = ".\data\source_archive_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Move-Item -LiteralPath .\data\source -Destination $archive
New-Item -ItemType Directory -Path .\data\source | Out-Null
.\.venv\Scripts\dataforge.exe generate --orders 3000 --seed 42
```

Review and retain the printed archive path; do not delete it as part of a reset. Then run the smoke script above. It revalidates source data before publishing a new active manifest. The PostgreSQL load/build are separate from source reset and do not reset database identity or dimension-key state.

## 3. Run analyses and tests

```powershell
Get-ChildItem .\sql\analysis\q*.sql | ForEach-Object {
  .\.venv\Scripts\dataforge.exe query $_.BaseName
}
.\.venv\Scripts\python.exe -m pytest -q
$env:RUN_POSTGRES_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest -q tests dashboards/P5/tests
.\.venv\Scripts\python.exe -m pytest -q -o faulthandler_timeout=60 tests dashboards/P5/tests
.\.venv\Scripts\ruff.exe check src tests scripts dashboards/P5
.\.venv\Scripts\python.exe -m compileall -q src tests scripts dashboards/P5
.\.venv\Scripts\python.exe -m pip check
```

The PostgreSQL integration suite uses isolated temporary databases. Remove the environment variable from that shell when finished with `Remove-Item Env:RUN_POSTGRES_TESTS`. The explicit `dashboards/P5/tests` path includes the offline Power BI path-configurator tests.

## 4. Refresh the Power BI snapshot

```powershell
.\.venv\Scripts\python.exe .\scripts\export_powerbi_gold.py --excel
```

The command reads the Gold tables in one read-only repeatable-read transaction and writes `data/powerbi_gold_export/DataForgeGold.xlsx`, the CSV equivalents and a manifest with row counts and SHA-256 digests. The generated files are ignored by Git. The PBIP source deliberately contains an unconfigured local-path sentinel. Before opening or refreshing, run the safe path preflight/configurator:

```powershell
.\.venv\Scripts\python.exe .\dashboards\P5\configure_workbook_path.py `
  --project .\dashboards\P5\DataForge\DataForge.pbip `
  --workbook .\data\powerbi_gold_export\DataForgeGold.xlsx `
  --dry-run
.\.venv\Scripts\python.exe .\dashboards\P5\configure_workbook_path.py `
  --project .\dashboards\P5\DataForge\DataForge.pbip `
  --workbook .\data\powerbi_gold_export\DataForgeGold.xlsx `
  --backup-dir .\.local\path_backups
.\.venv\Scripts\python.exe .\dashboards\P5\validate_source_pack.py `
  --project .\dashboards\P5\DataForge\DataForge.pbip `
  --workbook .\data\powerbi_gold_export\DataForgeGold.xlsx
```

The helper validates the synthetic marker, workbook SHA-256, sheet names and row counts before making a backup and atomically replacing only the TMDL path parameter. The dry run performs all preflight checks without changing files. Open the configured PBIP in Desktop and choose **Refresh**. If the workspace moves, run the same helper with the moved PBIP and workbook paths; the source pack does not claim a relative Power Query path.

For CSV-only exports without the optional dependency, omit `--excel`.

## 5. Optional real historical weather

Weather access is an explicit external HTTP call. Review the current provider terms and attribution before use. The adapter rejects missing, duplicate, extra, out-of-range and shuffled dates against the requested inclusive daily range before writing. To avoid mixing an API response into the canonical fixture, use a separate destination when invoking `dataforge.weather.fetch` directly for a smoke test. The CLI default writes under `data/source`; after an intentional default-path fetch, `generate` will refuse to overwrite the externally sourced weather table. Use the safe synthetic reset procedure above if a fresh seed-42 fixture is needed.

The API is coarse province/city-centre weather, not shipment-route weather. Keep its provider label and provenance artifacts; do not describe the weather/shipment association as causal. Before manifest promotion, ingestion verifies that the weather CSV, source marker, and complete provenance sidecar carry the same digest and row count. Fetch stages the CSV, marker, sidecar and raw response evidence before promotion, writes the CSV last, and restores the prior three files on caught promotion failures. If the process is interrupted, ingestion refuses the inconsistent set and leaves the active pointer unchanged. Inspect `data\source\.open_meteo\transactions\<id>\manifest.json`; for every file marked `present`, restore the corresponding backup file to `data\source` (the sidecar target is `data\source\.open_meteo\weather_provenance.json`). Retain the backup directory until the restored hashes agree, then rerun `dataforge ingest`. Repeating the explicit fetch after reviewing provider terms is also a recovery option.

## 6. Recovery checks

| Symptom | Check | Recovery |
|---|---|---|
| DB connection timeout | `docker compose ps`; confirm port `127.0.0.1:5433`; confirm `.env` host/port. | `docker compose up -d --wait`; inspect `docker compose logs --tail 100 postgres`. Do not print `.env` or rotate secrets just to troubleshoot a port mismatch. |
| Docker Desktop startup fails at `dockerInference` with “The file cannot be accessed by the system” | Confirm `docker info`, `docker compose ps`, and local Docker logs. The PostgreSQL container cannot start until the Docker engine is available. | Allow Docker Desktop to restart, then verify `docker info` and `docker compose up -d --wait`. This exact Windows AF_UNIX symptom is reported in [Docker Desktop feedback #554](https://github.com/docker/desktop-feedback/issues/554); on this host the engine recovered without a Windows restart. If the error persists, save work and restart Windows before retrying. If it still persists, use [Docker's troubleshooting guidance](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/) to gather local diagnostics without uploading them. Do not factory-reset Docker or delete its data volume for this error. |
| Ingest rejects a file | Read the quarantine row/reason and active-run manifest; verify columns, dates, types and duplicate keys. | Correct or regenerate the source, then rerun `dataforge ingest`. A failed validation must not promote a partial active run. |
| `db-load` rejects a legacy manifest without `bronze_sha256` | Confirm the active run is from a pre-P6 workspace and inspect its source/Parquet files. | Run full `dataforge ingest` without `--sources`; it validates current CSVs and only migrates a legacy Parquet file whose bytes match the deterministic serialization. If it reports a mismatch, preserve the artifact and source folder and restore from a trusted backup; do not delete or hand-edit manifests. |
| `db-load` reports a Parquet SHA/schema/row-count mismatch | Compare the active manifest, CSV hash and content-addressed Parquet artifact. | Preserve the failing files and active pointer, then restore a trusted source/Parquet backup or perform a separately reviewed full ingest from a trusted CSV. Failed preflight occurs before database mutation. |
| Weather source/provenance mismatch | Inspect `_DATAFORGE_SOURCE.json`, `weather_daily.csv` and `weather_provenance.json` hashes and row counts. | Preserve the current files. Restore a consistent set from backup or repeat the explicit weather fetch; ingest refuses the pair until all three agree. |
| Gold checks fail after load | Compare raw audit deltas, source hashes, FK/orphan checks and SCD2 interval coverage. | Resolve the source error and rerun the complete snapshot load; then rerun `db-build` and `db-check`. Raw load and mart build are separate transactions. |
| Power BI workbook not found | Check `data/powerbi_gold_export/DataForgeGold.xlsx`, its sibling `manifest.json`, and the TMDL parameter. | Run the export, run `configure_workbook_path.py` with the project and workbook paths, validate, then refresh Desktop. |
| Power BI totals disagree | Check refresh completion, visible date role, slicer path and the SQL control for the same filter/date semantics. | Re-export Gold, refresh, and compare order-item/payment/return measures separately. Never join row-level facts in a visual query. |

## 7. Shutdown

When finished, `docker compose stop` pauses the service while preserving its data volume. No cloud resources or remote report are part of the local workflow.
