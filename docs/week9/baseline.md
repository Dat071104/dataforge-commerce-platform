# Week 9 baseline

Baseline source: dbt manifest parsed from `origin/main` at `6b256f2` on 2026-11-18. Evidence is a local offline parse, not CI or live-GCP evidence. The reproducible counter is `scripts/week9_baseline.py`; it reads only `dbt/dataforge/target/manifest.json`.

| Measure | Baseline | Week 9 target | Counting rule |
|---|---:|---:|---|
| Models with a primary-key or grain uniqueness check | 14/16 (87.5%) | 16/16 (100%) | Generic `unique` tests plus the three named weather grain/request-key uniqueness tests. This counts uniqueness coverage; not-null coverage must also be checked when each key is hardened. |
| Models with a description | 14/16 (87.5%) | 16/16 (100%) | Non-empty model description in the manifest. |
| Gold model columns with a description | 12/22 (54.5%) | 22/22 (100%) | Models tagged `gold`; non-empty column description. Classification metadata is a separate W9 target. |
| Sources with freshness configured | 7/7 (100%) | 7/7 (100%) | Non-empty source freshness configuration in the manifest. |
| W9 fault fixtures mapped to the failure catalog | 0 | One failing fixture per blocking detector, plus F-N0 as a clean zero-alert control | Checked-in files under `tests/week9/faults/`; unrelated historical tests are not counted as W9 catalog fixtures. |

The manifest contains 16 models, 98 dbt test nodes (14 singular SQL tests), one dbt unit test, seven sources, and two snapshots. The existing unit-test fixtures are positive transformation examples; they do not establish a systematic, catalog-mapped fault matrix. The historical Week 7 candidate corruption script is not counted because it targets a Week 7 dataset and cannot be used as an isolated W9 drill.

Reproduction:

```powershell
cd dbt/dataforge
dbt deps --target offline --profiles-dir .
dbt parse --no-partial-parse --target offline --profiles-dir .
cd ../..
python scripts/week9_baseline.py
```

`dbt deps` reported that no packages are declared in `packages.yml`; `dbt parse` completed with dbt-core 1.11.17 and dbt-bigquery 1.11.3. The generated profile and parse artifacts are local-only and ignored by Git.
