# Syllabus-to-artifact coverage (Week 2 and 3)

Source: user-provided 12-week Intern Data Engineer syllabus, pages 2–3. Status below reflects local verification through 2026-11-06. Older phase notes remain historical; the current release record is [`docs/releases/v1.0-local.md`](releases/v1.0-local.md).

## P6 local hardening update (2026-11-04)

The table below preserves the original P5 evidence and traces syllabus coverage. P6 adds source overwrite/date-coverage regression tests, Parquet-byte integrity, fail-closed legacy-manifest migration, weather sidecar consistency, a Python 3.11 dependency lock, CI configuration and a configurable PBIP workbook path. P6.2 completed the three-page Desktop visual review and received **GO LOCAL**; current evidence and limitations are summarized in [`docs/releases/v1.0-local.md`](releases/v1.0-local.md).

| Mentor requirement | Artifact | State |
|---|---|---|
| Week 2 Python core / files / API | `src/dataforge/{generator,ingestion,weather}.py` | Implemented, unit-tested |
| CSV/JSON/Parquet | CSV ingest, Open-Meteo response parse, Parquet writer | Verified locally; 11 Parquet snapshots written |
| API retry / error / HTTP | `weather.fetch` | Mock-tested and one isolated Open-Meteo historical smoke verified; see P5 provenance receipt |
| Pandas/clean / validation | `ingestion.validate` | Implemented, source-validated |
| Type hints, pytest, Ruff | `src/`, `tests/`, `.github/workflows/ci.yml` | PostgreSQL-enabled suite: 54 passed on 2026-11-03 and again after recovery on 2026-11-04; default run: 50 passed, 4 skipped; Ruff passes |
| Mini-project 1 CSV → validate → Parquet | `dataforge generate` + `ingest` | 11-source local pipeline verified |
| Week 3 PostgreSQL advanced SQL | `sql/analysis/q01...q10` | All ten queries execute against PostgreSQL 16 |
| Index / EXPLAIN ANALYZE | `q10`, `sql/performance` | Script exists, no claimed performance gain |
| OLTP vs OLAP / 3NF vs star | `docs/architecture.md` | Explained in design |
| Kimball fact/dimension / SCD1 SCD2 | `sql/build/010_marts.sql` | Verified locally; SCD2 as-of/overlap/current-version checks run before raw commit |
| Data Vault / OBT comparison | `docs/MODELING_DECISIONS.md` | Documented brief comparative rationale |
| Power BI relationships / role-play / RLS | `dashboards/P5/` | 15 one-way relationships, 31 DAX measures and the South role; P6.2 matched 40 DAX/SQL controls and rendered all three current-source pages in Desktop |
| Mini-project 2 SQL/Power BI revenue dashboard | `sql/analysis/`, `dashboards/P5/DataForge/` | Ten SQL analyses verified; editable PBIP report rendered in Desktop (no PBIX binary or publish claimed) |
| SQL 60 minute test | External mentor evaluation | Not attempted / not claimed passed |
| Code review mini-projects 1+2 | Phase evidence retained locally | P6.2 received one independent **GO LOCAL** controller verdict; release summary is in `docs/releases/v1.0-local.md` |

## P6.2 final local acceptance (2026-11-06)

- All three current-source Power BI screenshots are included under `docs/screenshots/v1.0-local/`; the Operations image shows the final KPI-width layout, populated values/charts and a fully visible `Weather Source` label.
- The source-pack validator reports 10 model tables, 15 relationships, three pages and 33 visuals. The PBIR bounds/overlap receipt reports no overlaps or out-of-bounds visuals.
- Offline suite: 96 passed, 6 PostgreSQL skips. PostgreSQL integration suite: 102 passed using isolated temporary databases. Ruff, compileall and `pip check` passed.
- The previous 40/40 DAX/SQL, South RLS, delivery-date, engine refresh, relocation and pipeline receipts remain applicable. Numeric DAX, M partitions, relationships, RLS filters, database and upstream pipeline were not changed for this release.
