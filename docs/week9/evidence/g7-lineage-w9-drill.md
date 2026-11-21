# G7 — BigQuery lineage in the isolated W9 drill

**Status (2026-11-21):** Complete. Weather table-level lineage (below, 2026-11-19) plus synthetic-PII lineage captured 2026-11-21 11:52 +07: `restricted_pii.customer_profile → restricted_pii.customer_profile_restricted` and `→ pii_safe.dim_customer_profile_safe` (2 links, 2 processes, 5 policy-tagged raw columns; [JSON](g7-pii-lineage-20261121.json)). `datalineage.googleapis.com` was disabled at 2026-11-21 11:54:50 +07 and verified off read-only (final LINEAGE_DAY 3/5). The original 2026-11-19 status follows.

**Status (2026-11-19):** Partial; live GCP weather table-level lineage captured 2026-11-19. WIF lineage run `44460769849` completed `success` on exact head `a49802cdebee0c1a6ffa704d35baa61a1feb7070`; sanitized artifact `w9-lineage-summary-46-44460769849.json` confirms `status=PASS`, `dbt.build_status=PASS`, 50 dbt jobs with billing on all 50, 4 weather models, and 51 copied rows. PII policy-tag lineage remains pending I-4/G4. `LINEAGE_DAY 1/5`.

The Data Lineage and Dataplex APIs are enabled. The project-level BigQuery lineage-ingestion config has no override; Google documents BigQuery ingestion as enabled by default. The organization-level config is not readable with the current operator permission, but the live links and successful build artifact prove ingestion occurred in this project. The artifact reports 283,115,520 adapter bytes billed (270 MiB across 50 dbt jobs) plus three 10-MiB helper queries; the full retry billed 300 MiB.

## Observed links and event resources

Read-only `SearchLinks`, `batchSearchLinkProcesses`, and `lineageEvents.list` calls returned five distinct links and 18 event resources. The successful retry window was 2026-11-19 04:50Z (11:50 +07). BigQuery FQNs use the official `bigquery:project.dataset.table` form.

| Flow | Link ID | Process / BigQuery job ID | Run ID | Event IDs | Time (UTC) |
|---|---|---|---|---|---|
| `weather_mini3.weather_landing` → `w9_drill.weather_landing` | `p:1e882cbdcfccd332c1fd14fd741b4eca` | `sh-8a14cae047c7b164a04ef5dd26468c38` / `83e4431b-28ba-4991-909a-2d1b79cabaf8` | `c680e6ffd1e59fca530aef440c09fa6d` | `6ff1dfe95accee980585e8e4dc9f6784`, `81a074a38892907d431cf5ab71a0290e` | 04:50:15Z |
| `w9_drill.weather_landing` → `w9_drill.stg_weather_mini3_landing` | `p:70b0f14f4d37d1d3134b7a2881e90cd5` | `39898ae37c6132c60ead7e1daf732cf5` / `5dbba22a-4962-420b-93b0-ffb0f916d63c` | `222d1407f6f3d66fe2c03f90ab4bf064` | `16bc3d11de99b56255ed69e5e36c3c8e`, `eb71737498cb74ff3a97546ff21ec124` | 04:50:34Z |
| `w9_drill.stg_weather_mini3_landing` → `w9_drill.int_weather_daily` | `p:e9bef34c587878b8db3e2bd0b7363d71` | `sh-f5d3a1e10c6bd7f1060c2f95fd134882` / `3cda74f1-9bf9-41f0-acae-744d78031bc0` | `d43ae9247db93f49cf4c9154df4767bb` | `29afb5ecfae8b23da6b1500be111af52`, `f7d58eda0a922c40c3517f2f681b403f` | 04:50:41Z |
| `w9_drill.int_weather_daily` → `w9_drill.fct_mini3_weather_daily` | `p:7d34faff09aeef172b5fa06206e4106f` | `a87118e3782cfc5cc4600e7e78cda1cf` / `90c58e35-321b-4344-a201-6bd7b6df8311` | `e59c3eea70d923e9ad958ba7ef44a199` | `1d9c9c80366998b636547095c278de72`, `5f8784b95e6c4022332183fbfac2a042` | 04:50:48Z |
| `w9_drill.fct_mini3_weather_daily` → `w9_drill.mart_weather_province_daily` | `p:94fd239ace88bba2e9be2f54d7b822a1` | `28171116c49c4c03188cc3f383559d50` / `dc65313d-d6fe-4130-9619-03b4f9c268dc` | `7a20972c8bfbe1d5d17472eee3046b99` | `754949557350e89e34663911f0a854b3`, `c0fcffc516b8acf3bc2b76e37889f7b8` | 04:50:58Z |

The failed first attempt `44456977576` also created the source-copy link `weather_mini3.weather_landing` → `w9_drill.weather_landing` (events `234ba35a4978c9ce0bd43eeb4c49242b`, `dd7af3cade8570e7eb47d7ceb00e102d` at 04:17:15Z), but stopped before any dbt model build. It is recorded separately from the retry graph.

## Dataset and cost notes

- Read-only BigQuery metadata shows `w9_drill.weather_landing` has the validated `TIMESTAMP` `landed_at` type and 51 rows; the drill dataset contains only `weather_landing`, staging, silver, and the two Gold views. No W5/W7 resource was written.
- The 18 event resources correspond to at most 36 entity references. At the official example rate (≈USD 0.0004984/reference), the processing estimate is ≈USD 0.01794; this is not a billed amount. BigQuery billed 300 MiB on the successful retry (30 MiB helper queries + 270 MiB dbt adapter) and 30 MiB on the first failed attempt, 330 MiB total (≈USD 0.00197 list-price estimate). The USD 0.10 AF8 reserve covers this event volume, but metadata storage and actual Dataplex SKU remain **UNVERIFIED** because billing export access is unavailable.
- No screenshot or policy-tag lineage is claimed. Keep the API enabled only within AF8's timebox and disable after the full G7 evidence is captured or by day 5. Google notes BigQuery lineage can take 30 minutes to 24 hours to appear. [About data lineage](https://docs.cloud.google.com/knowledge-catalog/docs/about-data-lineage), [SearchLinks API](https://docs.cloud.google.com/knowledge-catalog/docs/reference/data-lineage/rest/v1/projects.locations.searchLinks), [lineage events API](https://docs.cloud.google.com/knowledge-catalog/docs/reference/data-lineage/rest/v1/projects.locations.processes.runs.lineageEvents/list), [Knowledge Catalog pricing](https://cloud.google.com/products/knowledge-catalog/pricing).
