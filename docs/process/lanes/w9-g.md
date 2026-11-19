# W9 Governance lane — G1–G9 evidence

**Branch:** `feat/w9-g-2` from `origin/main` `3a20050e813700cd0a050c69aa1dbd652ca9fc08`

**Status:** G1–G5 merged in PR #45. G6/G8/G9 local artifacts are implemented. G6 Actions workflow, G4 live access, G3 Terraform plan/apply, and G CI remain **UNVERIFIED/PENDING**. The integrator's WIF dbt dispatch produced the isolated W9 weather lineage graph; its terminal GitHub conclusion and the PII policy-tag lineage are still pending.

**Data boundary:** synthetic-only; no GCP query/load, WIF token request, IAM mutation, API enablement, secret creation, local OpenMetadata/Docker run, or production write was performed. OpenMetadata runs only through the GitHub Actions workflow, which remains unrun in this worker block.

## Changed files

- `governance/classification.yml` — official legal-source status update.
- `src/dataforge/privacy/__init__.py`
- `src/dataforge/privacy/erasure.py`
- `scripts/week9_pii_erasure.py`
- `scripts/week9_catalog_fallback.py`
- `tests/week9/governance/test_week9_governance.py`
- `.github/workflows/week9-catalog.yml`
- `governance/openmetadata/docker-compose.yml`
- `governance/openmetadata/dataforge_service.json`
- `governance/openmetadata/dbt_ingestion.yaml`
- `governance/openmetadata/bigquery_ingestion.yaml`
- `governance/openmetadata/README.md`
- `docs/process/lanes/w9-g.md`

G1–G5 artifacts are already in PR #45 and are not part of this branch delta. This branch does not edit Q’s `dbt/dataforge/models/week9_tests.yml`.

## G1 — classification

Every declared source, model, snapshot, and Gold output column has `meta.classification`, `meta.pii_type`, `meta.purpose`, and `meta.retention_days`. The YAML registry is checked against the dbt YAML so the two copies cannot silently drift.

| Coverage set | Objects | Columns | Classified |
|---|---:|---:|---:|
| Sources | 8 tables | 110 | 110 |
| Models | 18 | 213 | 213 |
| Snapshots | 2 | 28 | 28 |
| Gold outputs | 5 | 55 | 55 (100%) |
| **Total** | — | **351** | **351** |

The 55 Gold columns are included in the 351 total columns.

Legal mapping is based on official text, with application to a real deployment left for privacy counsel:

- Law 91/2025/QH15 took effect 2026-01-01. Article 20 defines cross-border-transfer cases and related impact-assessment requirements; Article 39 contains limited transition provisions for prior consent/agreements and already accepted impact-assessment dossiers. [Official law record](https://vanban.chinhphu.vn/?docid=214590&pageid=27160); [official text PDF](https://congbao.chinhphu.vn/tai-ve-van-ban-so-91-2025-qh15-45578-57730?format=pdf).
- Decree 356/2025/NĐ-CP took effect 2026-01-01. Article 42(2) states that Decree 13/2023/NĐ-CP ceases to be effective on that date; Decree 13 is not treated as generally active after 2025. [Official Decree 356 record](https://vanban.chinhphu.vn/?docid=216387&pageid=27160&typegroupid=4); [official Decree 356 PDF](https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/01/356-nd.signed.pdf).
- `us-central1` is in the United States. If the project handled personal data collected in Vietnam, storage or processing there would be a cross-border-transfer scenario under Article 20; no exception is assumed. This lane uses synthetic data only.
- The phone fixture uses `+84-000-` as an intentionally invalid, fixture-only mobile prefix outside the ranges listed in the Ministry of Information and Communications’ mobile-prefix notice. The notice is not an exhaustive allocation registry, so no live or routable phone number is claimed. [MIC prefix notice](https://english.mic.gov.vn/vietnamese-mobile-carriers-roll-out-new-prefixes-197137770.htm).

## G2–G3 — synthetic profiles, pseudonymization, masking

`src/dataforge/privacy/synthetic.py` uses Faker `vi_VN`, a fixed seed, and an in-memory generator. CCCD fixtures use reserved prefix `999`; e-mails use `@example.com`; phone values use the documented fixture-only `+84-000-` prefix. The synthetic row label is `data_classification=synthetic`. Raw values load only to `restricted_pii.customer_profile`, with `WRITE_EMPTY`; the default CLI prints a local plan and emits no raw values.

`src/dataforge/privacy/pseudonymize.py` computes HMAC-SHA256 during generation/load and reads key bytes only from Secret Manager secret `w9-pii-hmac-key`. The key is not put in SQL, logs, or receipts. The restricted-only view `restricted_pii.customer_profile_restricted` attaches `policy_tags` to the five direct identifiers and enables column `persist_docs`. `full_name` and `cccd` share one `ALWAYS_NULL` policy tag; e-mail, phone, and birth date use separate policies. This keeps the Terraform plan at four tags and four data policies, within the AF4 cap. Tag names come from Terraform outputs through `DATAFORGE_W9_POLICY_TAG_IDENTITY`, `..._EMAIL`, `..._PHONE`, and `..._BIRTH_DATE`. If a variable is absent, dbt sees `UNCONFIGURED`, so materialization must fail until the integrator supplies real tag names. The safe dbt model writes only `customer_token`, `age_band`, `province_id`, `email_masked`, and the synthetic label to `pii_safe.dim_customer_profile_safe`.

`cloud/terraform/week9_dataops/policy_tags.tf` is an opt-in HCL plan fragment with `week9_pii_enabled=false`. It references O1’s `google_bigquery_dataset.restricted_pii` and `.pii_safe`; it does not create duplicate dataset resources. It defines a taxonomy and mask policies for name, CCCD, e-mail, phone, and birth date. CCCD uses `ALWAYS_NULL`, because an unkeyed SHA-256 of a 10^9-suffix fixture space is brute-forceable; the Secret Manager HMAC token is the approved join key, and raw CCCD stays visible only to the privileged identity. A separate `week9_pii_test_impersonation_enabled=false` flag gates temporary operator-only TokenCreator bindings on the two test SAs; no CI identity receives that role. The integrator should disable the flag after G4 verification. No Terraform plan or apply was run. Google documents policy-tag-based masking and the provider exposes a BigQuery Data Policy Terraform resource, but the project APIs are currently disabled, so project-side feasibility remains UNVERIFIED. [BigQuery masking overview](https://docs.cloud.google.com/bigquery/docs/column-data-masking-intro); [Terraform Data Policy resource](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/bigquery_datapolicy_data_policy).

The `generate_schema_name.sql` macro sends only `pii_safe`, `restricted_pii`, and Q’s `dataforge_dq` to their exact dataset names and preserves the existing `target.schema_custom_schema` naming path for every other custom schema. This is a cross-cutting dbt macro and needs integrator review; no dbt parse/build was run.

## G4 — access boundary

`scripts/week9_verify_access.py` supports an offline plan by default and a separately gated `--execute` mode. It checks that the `pii_safe` table schema has no raw identity fields, the analyst reads masked/generalized rows, the analyst is denied `restricted_pii`, and the privileged test SA reads the synthetic raw fixture. The script emits only result counts and booleans. No impersonation or live query was run; all G4 live results are **UNVERIFIED / INTEGRATOR_ACTION_REQUIRED**.

Each of the three live query probes uses a BigQuery `QueryJobConfig` with `maximum_bytes_billed=1 GiB`; labels identify the W9 G4 action for cost review. No query result values are printed.

After the integrator provisions the two test SAs and approves the IAM plan, the exact script command is:

```powershell
$env:PYTHONPATH = 'src'
$env:DATAFORGE_W9_PII_ACCESS_TEST_ENABLED = 'true'
python scripts/week9_verify_access.py --execute
```

The script impersonates the AF4-authorized identities `dataforge-w9-analyst-test` and `dataforge-w9-privileged-test`. Its queries are:

```sql
-- Analyst: safe, masked/generalized mart only
SELECT customer_token, age_band, province_id, email_masked
FROM `dataforge-p7-lab-d0f725.pii_safe.dim_customer_profile_safe`
ORDER BY customer_token
LIMIT 20;

-- Analyst: this must return permission denied
SELECT full_name, cccd, email, phone, birth_date
FROM `dataforge-p7-lab-d0f725.restricted_pii.customer_profile`
LIMIT 1;

-- Privileged test SA: aggregate-only proof that stored rows use synthetic patterns
SELECT COUNT(*) AS row_count,
       COUNTIF(REGEXP_CONTAINS(cccd, r'^999[0-9]{9}$')) AS reserved_cccd_count,
       COUNTIF(REGEXP_CONTAINS(email, r'^[^@]+@example\.com$')) AS example_email_count,
       COUNTIF(STARTS_WITH(phone, '+84-000-')) AS synthetic_phone_count
FROM `dataforge-p7-lab-d0f725.restricted_pii.customer_profile`;
```

No query returns raw values in the verifier receipt. The synthetic loader’s explicit future command is `python scripts/week9_pii_generate.py --execute`; it requires `DATAFORGE_W9_PII_LOAD_ENABLED=true`, the four `DATAFORGE_W9_POLICY_TAG_{IDENTITY,EMAIL,PHONE,BIRTH_DATE}` values, and the Secret Manager key. It was not run.

## G5 — manifest/model PII guard

`scripts/week9_pii_guard.py` reads dbt `manifest.json`, follows model-to-source dependencies, and checks every model output column’s `meta.classification` and `meta.pii_type`. It rejects restricted/direct PII in models outside `restricted_pii`, unclassified manifest columns, and indirect or pseudonymous customer identifiers classified as public. Findings contain model, column, classification, type, lineage boolean, and reason only; no values are emitted.

The retained F13 manifest fixture projects a raw e-mail column with `classification: public` and `pii_type: email`; it must fail. The separate safe-masked manifest fixture contains only the safe mart fields and passes. The guard also allows a `customer_id` output when it remains `confidential` and typed as `indirect_customer_identifier`; it blocks the same identifier if classified public.

## G6 — OpenMetadata catalog in GitHub Actions

`.github/workflows/week9-catalog.yml` is the only runner for the OpenMetadata profile. It uses a credential-free dbt `offline` parse, then a temporary OpenMetadata 2.0.7 server with Postgres 16 and OpenSearch 2.19, with no Airflow service. The version-matched CLI ingests the CI `manifest.json` and then attempts BigQuery metadata ingestion under service name `dataforge_w9_catalog`. The dbt manifest contains model metadata and dbt lineage; this is distinct from G7 execution lineage.

The BigQuery connector enumerates project dataset IDs, then applies the schema filter before listing tables ([enumeration and filter](https://github.com/open-metadata/OpenMetadata/blob/2.0.7-release/ingestion/src/metadata/ingestion/source/database/bigquery/metadata.py#L654-L681), [dataset-filter path](https://github.com/open-metadata/OpenMetadata/blob/2.0.7-release/ingestion/src/metadata/ingestion/source/database/bigquery/metadata.py#L817-L840)). Dataset-ID listing is metadata-only under AF2's project-scoped `roles/bigquery.metadataViewer`; table metadata is restricted to `w9_drill`, `dataforge_dq`, `restricted_pii`, `pii_safe`, and `dbt_ci_pr_*`. No W7 table metadata is queried or included in evidence. Profiler/sample data, usage/query logs, policy tags, DDL, owners, and stored procedures are disabled; no table rows are requested and no source resource is modified. WIF uses `W9_WIF_PROVIDER` and `W9_META_READ_SA_EMAIL` only in this Actions workflow. No IAM is expanded.

OpenMetadata documents additional metadata permissions including `bigquery.tables.getData`, `bigquery.jobs.create`, and `bigquery.jobs.listAll`, beyond AF2's metadata viewer/Data Catalog viewer grants. The workflow suppresses raw connector logs and reports only a recognized denied permission or a generic failure category; a permission denial becomes the sanitized `DATAPLEX_FALLBACK_REASON`. BigQuery metadata ingestion remains **UNVERIFIED** until the G6 workflow runs. Dataplex execution lineage is separate; the integrator has now captured table-level weather links in `w9_drill`, while G7 policy-tag lineage remains pending. [OpenMetadata 2.0 dbt CLI docs](https://docs.open-metadata.org/v2.0.x/connectors/database/dbt/run-dbt-workflow-externally); [BigQuery connector permissions](https://docs.open-metadata.org/v2.0.x/connectors/database/bigquery).

## G7 — Dataplex/BigQuery lineage

**PARTIAL — live GCP (isolated dataset).** On 2026-11-19, the integrator's WIF lineage dispatch refreshed `w9_drill.weather_landing` and materialized staging, silver, and gold weather relations. Read-only Data Lineage API searches show five distinct links and 18 event resources. Link IDs, process/run IDs, BigQuery job IDs, event IDs/times, and source/target FQNs are recorded in `docs/week9/evidence/g7-lineage-w9-drill.md`. The final GitHub workflow conclusion and sanitized cost artifact are **UNVERIFIED** after a GitHub API connection reset. This proves the weather table graph only; PII policy-tag lineage remains pending G3/G4. The API is enabled for LINEAGE_DAY 1/5; Dataplex SKU remains **UNVERIFIED**. Disable after full G7 evidence is captured or by day 5, whichever comes first.

## G8 — current legal-source check

The legal mapping in `governance/classification.yml` was reviewed on 2026-11-19 against official records. Law 91/2025/QH15 took effect 2026-01-01; Article 20 covers cross-border personal-data transfer and Article 39 contains limited transition treatment. Decree 356/2025/NĐ-CP also took effect 2026-01-01; its Article 42(2) repeals Decree 13/2023/NĐ-CP. Decree 13 is not generally in force after that date; only the stated Article 39 transition applies.

Two later enforcement decrees are included so the register is current. Decree 330/2026/NĐ-CP took effect 2026-08-19; the official Government summary lists personal-data deletion/destruction/de-identification and cross-border transfer among its enforcement topics. Decree 363/2026/NĐ-CP took effect 2026-11-11; the official Government summary says it excludes conduct handled by the separate cybersecurity/personal-data penalty decree. The official metadata and summaries were available, but the signed 330/363 PDFs were too large for this review fetch; exact article/penalty mapping is marked `LEGAL_UNVERIFIED`. This is a source map, not legal advice. [Law 91 record](https://vanban.chinhphu.vn/?docid=214590&pageid=27160); [Decree 356 record](https://vanban.chinhphu.vn/?docid=216387&pageid=27160&typegroupid=4); [Decree 330 record](https://vanban.chinhphu.vn/?classid=1&docid=219266&pageid=27160&typegroupid=4); [Decree 330 Government summary](https://baochinhphu.vn/muc-xu-phat-vi-pham-hanh-chinh-doi-voi-hanh-vi-vi-pham-ve-bao-ve-du-lieu-ca-nhan-102260822154959691.htm); [Decree 363 record](https://vanban.chinhphu.vn/?docid=219598&pageid=27160); [Decree 363 Government summary](https://baochinhphu.vn/chi-dao-dieu-hanh-cua-chinh-phu-thu-tuong-chinh-phu-ngay-23-9-2026-102260923060636776.htm).

## G9 — P2 synthetic erasure drill

`src/dataforge/privacy/erasure.py` and `scripts/week9_pii_erasure.py` model a dry-run across `restricted_pii.customer_profile`, the restricted view, `pii_safe.dim_customer_profile_safe`, and a synthetic SCD2 snapshot relation. Unit fixtures use one synthetic profile and two snapshot versions; the dry-run reports counts only, and the optional local simulation removes those in-memory rows only. It never calls BigQuery, deletes cloud data, or logs the subject token. The current staging relation is a view, so a real erasure should delete from raw and verify the re-evaluated view is empty; any materialized staging copy requires its own purge.

BigQuery time travel keeps changed/deleted data recoverable for seven days by default; the configured window can be 2–7 days, followed by an additional seven-day fail-safe period. Thus a row delete is not immediate physical erasure. The shared HMAC key is pseudonymization, not encryption: deleting it breaks joins for all subjects and does not erase raw or historical data. Per-subject crypto-shredding would need a separately designed per-subject encryption key/DEK and is not implemented. No live erasure or crypto-shred was run. [BigQuery time travel/fail-safe docs](https://docs.cloud.google.com/bigquery/docs/time-travel).

## Checks and evidence

| Command | Result |
|---|---|
| `python -m pytest tests/week9/governance -q` | Exit 0; 17 passed. |
| `python -m ruff check src/dataforge/privacy scripts/week9_catalog_fallback.py scripts/week9_classification_coverage.py scripts/week9_pii_guard.py scripts/week9_pii_generate.py scripts/week9_pii_erasure.py scripts/week9_verify_access.py tests/week9/governance` | Exit 0; all checks passed. |
| `python -m compileall -q src/dataforge/privacy scripts/week9_catalog_fallback.py scripts/week9_classification_coverage.py scripts/week9_pii_guard.py scripts/week9_pii_generate.py scripts/week9_pii_erasure.py scripts/week9_verify_access.py tests/week9/governance` | Exit 0. |
| `$env:PYTHONPATH='src'; python scripts/week9_classification_coverage.py` | Exit 0; 351 total columns classified (110 source, 213 model, 28 snapshot); 55 Gold columns are a subset of model columns, all complete. |
| `$env:PYTHONPATH='src'; python scripts/week9_pii_guard.py --manifest tests/week9/governance/fixtures/safe_masked_manifest.json` | Exit 0; 1 model, 1 restricted source, 0 findings. |
| `$env:PYTHONPATH='src'; python scripts/week9_pii_guard.py --manifest tests/week9/governance/fixtures/f13_public_email_manifest.json` | Exit 1 as expected; one sanitized F13 finding for the public e-mail column. |
| `$env:PYTHONPATH='src'; python scripts/week9_pii_generate.py` | Exit 0; local synthetic plan, 5 rows, cloud writes false, PII values emitted false. |
| `$env:PYTHONPATH='src'; python scripts/week9_verify_access.py` | Exit 0; plan status UNVERIFIED, live resources absent, no values logged. |
| `$env:PYTHONPATH='src'; python scripts/week9_pii_erasure.py` | Exit 0; synthetic dry-run plan across raw, staging-view, mart, and two snapshot versions; no cloud mutation. |
| `$env:PYTHONPATH='src'; python scripts/week9_pii_erasure.py --simulate-local-delete` | Exit 0; in-memory fixture cleared across all four layers; this is unit simulation only. |
| Static YAML/JSON checks for catalog workflow, stack, and configs | Exit 0 in unit suite; no Docker/OpenMetadata process was launched locally. |
| YAML/JSON parse of classification, six dbt YAML files, four OpenMetadata/GHA YAML files, and service JSON | Exit 0; 11 YAML and 1 JSON parsed. |
| `git diff --check` | Exit 0. |
| G2/G6 GitHub Actions run ID | **UNVERIFIED**; workflow not run in this worker block. |
| dbt build / G7 weather links | Integrator's WIF dispatch `44460769849` materialized W9 weather tables and exposed 5 links / 18 events; terminal CI status and billed-job summary **UNVERIFIED** pending GitHub reconnection. |
| G3/G4, G6, PII-tag lineage, Q8 plan/apply, live delete, API hierarchy check | Not run or **UNVERIFIED/PENDING_INTEGRATOR**. |

### `check_id` ↔ fixture mapping

| Check ID | Fixture or evidence |
|---|---|
| `G1-CLASSIFICATION-001` | `governance/classification.yml` checked against eight source tables, 18 models, two snapshots, and all 55 Gold columns. |
| `G2-PII-001` | In-memory fixed-seed `vi_VN` profiles from `generate_customer_profiles`; no persistent raw fixture. |
| `G2-PII-PLAN-001` | Local-only receipt for `restricted_pii.customer_profile`; no cloud write. |
| `G3-PSEUDONYM-001` | Unit-only reserved-prefix CCCD input; output token is HMAC-SHA256 and never printed. |
| `G3-POLICY-TAG-001` | `models/pii/restricted/schema.yml` has column policy tags for the five raw PII fields and persists column docs; name and CCCD share the identity tag. |
| `AF4-POLICY-CAP-001` | `policy_tags.tf` and the loader mapping define four policy-tag/data-policy groups: identity, e-mail, phone, and birth date. |
| `AF4-LOADER-TAGS-001` | Loader requires four valid policy-tag environment values and rejects a missing identity tag. |
| `G3-DBT-SCHEMA-NAME-001` | Static regression check for exact `pii_safe`, `restricted_pii`, and `dataforge_dq` schema branches plus unchanged non-PII fallback. |
| `G4-ACCESS-PLAN-001` | Offline access plan for `restricted_pii.customer_profile` and `pii_safe.dim_customer_profile_safe`; no live identity used. |
| `G5-F13-001` | `tests/week9/governance/fixtures/f13_public_email_manifest.json`; guard detects its raw e-mail output. `safe_masked_manifest.json` is the passing comparison. |
| `G5-INDIRECT-CUSTOMER-001` | Synthetic manifest mutation proves confidential `customer_id` is allowed while public classification fails. |
| `G6-OM-CATALOG-001` | Static checks confirm Actions-only dbt and BigQuery recipes, W9 dataset filters, metadata-only flags, WIF SA wiring, and sanitized fallback. GHA run is unverified; dataset-ID enumeration is permitted metadata, then the schema filter limits table metadata to W9 datasets. |
| `G6-OM-PERMISSION-FALLBACK-001` | Synthetic connector log with a `bigquery.tables.getData` denial yields only that permission name in the Dataplex fallback; table/dataset names are omitted. |
| `G6-OM-UNKNOWN-FAILURE-001` | Generic synthetic connector failure produces a sanitized UNVERIFIED receipt without raw log contents. |
| `G7-DATAPLEX-LINEAGE-001` | Live GCP weather chain in `w9_drill`: five links / 18 event resources; evidence file has event/process/run IDs, timestamps, and source/target FQNs. PII policy-tag lineage and Dataplex SKU remain UNVERIFIED. |
| `G8-LEGAL-SOURCE-001` | Official records and summaries for Law 91, Decree 356, Decree 330, and Decree 363; article-level 330/363 crosswalk is explicitly LEGAL_UNVERIFIED. |
| `G9-P2-ERASURE-PLAN-001` | In-memory synthetic erasure plan matches raw/staging/mart and two SCD2 versions; dry-run only. |
| `G9-P2-ERASURE-SIM-001` | Local-only simulation removes all fixture rows for the synthetic HMAC-shaped token; no cloud call. |

## CI, risks, and integrator actions

### G-PR1 DataOps lint RCA

DataOps lint run `44374331732` failed only SQLFluff LT05 on the two model-level `config(...)` lines (88 and 95 characters versus the 80-character limit). Both calls were reformatted across lines without changing their configuration values or SQL semantics. No cloud action was involved.

Focused local recheck with SQLFluff 3.4.2 passed for both files using the repository BigQuery/Jinja dialect settings.

- G-PR1 #45 head `e4e4f06` ran DataForge push/PR `44377779560` / `44377789863` and Week 7 `44377789915`; offline regression failed because `test_model_pk_config.py` still referenced the removed `models/week9_tests.yml`. Pages `44377789937` and DataOps lint/Gitleaks/toolbox `44377789868` passed. Week 7 dbt parse and Airflow reference passed on that head. The integrator updated the test path locally; the post-fix head still needs exact-head CI.
- HCL plan syntax and provider resource behavior: **UNVERIFIED**; Terraform was not planned or applied. `week9_pii_policy_tags.tf` stays opt-in false and must be reviewed alongside O1’s dataset resource names. O should keep deletion protection on both datasets.
- `generate_schema_name.sql` is the only cross-cutting dbt change. Review its exact-schema exception before merge and run dbt parse/build after profile/dataset setup.
- Existing Week-7 models still carry `customer_id`, classified as confidential indirect identifier. This is intentionally allowed for order-to-cash grain/joins and is not a direct name/contact/CCCD field; public classification is blocked. Privacy owners should review whether any future public mart needs tokenized IDs instead.
- `retention_days` is classification metadata. Physical retention is only proposed for the raw dataset through O1’s seven-day default table expiration; other dataset/model retention is not enforced or verified in this lane.
- Data Catalog and BigQuery Data Policy API state, applied policy tags, masking behavior, analyst denial, and privileged access were not live-tested. No API was enabled and no cloud resource was created.
- The configured US region would make real Vietnamese personal-data storage/processing a cross-border-transfer case under Law 91 Article 20. This work uses only synthetic data; privacy counsel must review any real-data proposal and applicable exceptions.

G6 local evidence is limited to workflow/config and synthetic sanitizer tests; both the dbt manifest and BigQuery metadata ingestion await Actions. AF2's published connector-permission comparison includes `tables.getData`, `jobs.create`, and `jobs.listAll`; a denial is expected to be reported without changing IAM. The workflow uses repository variables `W9_WIF_PROVIDER` and `W9_META_READ_SA_EMAIL`, removes the generated credential file in an `always()` cleanup step, and prints no raw connector logs. WIF risk: the job requests `id-token: write`, and the currently applied provider allows `pull_request` for this workflow. Keep G6 on `workflow_dispatch`/main only until the provider event update is reviewed and applied; a workflow `if` check alone is insufficient. [GitHub OIDC permissions](https://docs.github.com/en/actions/reference/security/oidc); [fork workflow behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflows-in-forked-repositories). G9 is only a modelled synthetic drill.

Integrator actions before G2 close-out:

1. Run `week9-catalog.yml` on the exact G2 PR head and capture the Actions run ID, dbt-manifest result, and sanitized BigQuery metadata receipt. If the connector reports a specific denied permission, preserve only that permission name in `DATAPLEX_FALLBACK_REASON`; do not add IAM.
2. Confirm the connector used the W9 schema allowlist (`w9_drill`, `dataforge_dq`, `restricted_pii`, `pii_safe`, `dbt_ci_pr_*`) and that no W7 table metadata appears in its evidence. If the allowlist does not hold in the pinned connector, stop the connector and use the Dataplex fallback for G7 lineage.
3. For G7, the weather lineage links are captured. After G3/G4, capture the PII policy-tag lineage and reconcile the final CI artifact/cost. Keep the API within the AF8 timebox and disable it after full evidence or by day 5.
4. Review Decree 330/363 signed texts with privacy counsel before relying on the summarized enforcement map. The file flags article-level details as LEGAL_UNVERIFIED.
5. Treat G9 as planning/test evidence only. Any real-data erasure needs an authorized operational runbook, time-travel/fail-safe disposition, full SCD2-version check, and per-subject encryption-key design if crypto-shredding is required.

Worker G stops before push/merge; integrator owns the G2 PR sequence and live G7 action. This branch adds G6–G9 artifacts. The weather lineage graph is now live GCP evidence; G6 catalog ingestion, G4 access tests, G3/Q8 plan/apply, and PII-tag lineage remain pending.

## Integrator schema reconciliation — 2026-11-19

Exact-head dbt parse in G-PR1 first found `stg_week5_run_events` defined in both `models/schema.yml` and Q's `models/week9_tests.yml`. The same Q file also duplicated `stg_week5_pipeline_checkpoints`, which already has G classification metadata. The integrator moved both Q `unique`/`not_null` test blocks into the existing G-owned model entries, preserving the check IDs, severity, and expressions, then removed the duplicate `week9_tests.yml`. The Q key-config unit test now reads the consolidated `schema.yml`; its assertions are unchanged. The dbt parse and Pages/Week 7 parse checks passed on head `e4e4f06`; the offline suite then failed because the Q test path still named the deleted file. The integrator updated that path locally; post-fix exact-head rerun is pending.

The scheduler retry scenario showed one sensor-state mismatch on the earlier GPR1 head `cc371f0`, then passed on `e4e4f06` without changes to the Airflow harness or Q's G0 runtime path. Worker Q confirmed the harness did not invoke the Q weather-job code. The cause remains unverified; record this as a non-repeatable CI failure, not a confirmed code fix.
