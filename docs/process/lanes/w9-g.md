# W9 Governance lane — G1–G5 evidence

**Branch:** `feat/w9-g-1` from `origin/main` `ab345f7`  
**Status:** G1–G5 local implementation complete; G4 live access, Terraform plan/apply, dbt build, CI, and G-PR1 remain **UNVERIFIED**.  
**Data boundary:** synthetic-only; no GCP query, load, IAM mutation, API enablement, secret creation, or production write was performed.

## Changed files

- `governance/classification.yml`
- `dbt/dataforge/models/sources.yml`
- `dbt/dataforge/models/schema.yml`
- `dbt/dataforge/models/weather/marts/schema.yml`
- `dbt/dataforge/models/pii/marts/dim_customer_profile_safe.sql`
- `dbt/dataforge/models/pii/marts/schema.yml`
- `dbt/dataforge/models/pii/restricted/stg_customer_profile_restricted.sql`
- `dbt/dataforge/models/pii/restricted/schema.yml`
- `dbt/dataforge/macros/pii_masks.sql`
- `dbt/dataforge/macros/generate_schema_name.sql`
- `src/dataforge/privacy/__init__.py`
- `src/dataforge/privacy/synthetic.py`
- `src/dataforge/privacy/pseudonymize.py`
- `scripts/week9_pii_generate.py`
- `scripts/week9_pii_guard.py`
- `scripts/week9_classification_coverage.py`
- `scripts/week9_verify_access.py`
- `tests/week9/governance/test_week9_governance.py`
- `tests/week9/governance/fixtures/f13_public_email_manifest.json`
- `tests/week9/governance/fixtures/safe_masked_manifest.json`
- `cloud/terraform/week9_dataops/policy_tags.tf`
- `pyproject.toml` and `requirements-py311.lock` (pin Faker and add YAML/Jinja validation dependencies)
- `docs/process/lanes/w9-g.md`

The three existing dbt YAML files remain LF as stored in Git; `git diff --ignore-space-at-eol --numstat` showed only intended inserted metadata lines. The lane does not edit Q’s `dbt/dataforge/models/week9_tests.yml`.

## G1 — classification

Every declared source, model, snapshot, and Gold output column has `meta.classification`, `meta.pii_type`, `meta.purpose`, and `meta.retention_days`. The YAML registry is checked against the dbt YAML so the two copies cannot silently drift.

| Coverage set | Objects | Columns | Classified |
|---|---:|---:|---:|
| Sources | 8 tables | 110 | 110 |
| Models | 18 | 213 | 213 |
| Snapshots | 2 | 28 | 28 |
| Gold outputs | 5 | 55 | 55 (100%) |
| **Total** | — | **351** | **351** |

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

After the integrator provisions the two test SAs and approves the IAM plan, the exact script command is:

```powershell
$env:PYTHONPATH = 'src'
$env:DATAFORGE_W9_PII_ACCESS_TEST_ENABLED = 'true'
python scripts/week9_verify_access.py --execute
```

The script impersonates `dataforge-w9-pii-analyst-test` and `dataforge-w9-pii-privileged-test`. Its queries are:

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

## Checks and evidence

| Command | Result |
|---|---|
| `python -m pytest tests/week9/governance -q` | Exit 0; 11 passed. |
| `python -m ruff check src/dataforge/privacy scripts/week9_classification_coverage.py scripts/week9_pii_guard.py scripts/week9_pii_generate.py scripts/week9_verify_access.py tests/week9/governance` | Exit 0; all checks passed. |
| `python -m compileall -q src/dataforge/privacy scripts/week9_classification_coverage.py scripts/week9_pii_guard.py scripts/week9_pii_generate.py scripts/week9_verify_access.py tests/week9/governance` | Exit 0. |
| `$env:PYTHONPATH='src'; python scripts/week9_classification_coverage.py` | Exit 0; 351/351 columns and 55/55 Gold columns complete. |
| `$env:PYTHONPATH='src'; python scripts/week9_pii_guard.py --manifest tests/week9/governance/fixtures/safe_masked_manifest.json` | Exit 0; 1 model, 1 restricted source, 0 findings. |
| `$env:PYTHONPATH='src'; python scripts/week9_pii_guard.py --manifest tests/week9/governance/fixtures/f13_public_email_manifest.json` | Exit 1 as expected; one sanitized F13 finding for the public e-mail column. |
| `$env:PYTHONPATH='src'; python scripts/week9_pii_generate.py` | Exit 0; local synthetic plan, 5 rows, cloud writes false, PII values emitted false. |
| `$env:PYTHONPATH='src'; python scripts/week9_verify_access.py` | Exit 0; plan status UNVERIFIED, live resources absent, no values logged. |
| YAML parse of classification + five dbt YAML files | Exit 0; 6 files parsed. |
| `git diff --check` | Exit 0. |
| Terraform plan/apply, dbt parse/build, live BigQuery load/query, API checks | Not run; **UNVERIFIED** pending integrator preflight. |

### `check_id` ↔ fixture mapping

| Check ID | Fixture or evidence |
|---|---|
| `G1-CLASSIFICATION-001` | `governance/classification.yml` checked against eight source tables, 17 models, two snapshots, and all 55 Gold columns. |
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

## CI, risks, and integrator actions

- CI run IDs: **UNVERIFIED**. Worker G did not push/open a PR; root reported `github.com:443` unavailable and will batch remote operations later.
- HCL plan syntax and provider resource behavior: **UNVERIFIED**; Terraform was not planned or applied. `week9_pii_policy_tags.tf` stays opt-in false and must be reviewed alongside O1’s dataset resource names. O should keep deletion protection on both datasets.
- `generate_schema_name.sql` is the only cross-cutting dbt change. Review its exact-schema exception before merge and run dbt parse/build after profile/dataset setup.
- Existing Week-7 models still carry `customer_id`, classified as confidential indirect identifier. This is intentionally allowed for order-to-cash grain/joins and is not a direct name/contact/CCCD field; public classification is blocked. Privacy owners should review whether any future public mart needs tokenized IDs instead.
- `retention_days` is classification metadata. Physical retention is only proposed for the raw dataset through O1’s seven-day default table expiration; other dataset/model retention is not enforced or verified in this lane.
- Data Catalog and BigQuery Data Policy API state, applied policy tags, masking behavior, analyst denial, and privileged access were not live-tested. No API was enabled and no cloud resource was created.
- The configured US region would make real Vietnamese personal-data storage/processing a cross-border-transfer case under Law 91 Article 20. This work uses only synthetic data; privacy counsel must review any real-data proposal and applicable exceptions.

Integrator actions before G-PR1 acceptance:

1. Integrate `policy_tags.tf` with O1’s protected `restricted_pii` and `pii_safe` datasets, verify exact provider schema/resource names, and review the temporary operator-only TokenCreator bindings. Enable `week9_pii_test_impersonation_enabled` only for G4, then disable it. Keep CI excluded.
2. Complete API and identity preflight; create `w9-pii-hmac-key` through the approved secret process and supply the policy-tag output names to the loader environment.
3. Load the fixed-seed synthetic fixture once into `restricted_pii.customer_profile`, build only `dim_customer_profile_safe` into exactly `pii_safe`, and confirm the output contains no raw fields.
4. Run the G4 impersonated access check, capture only counts/booleans, and record its output with the live resource IDs. If policy-tag masking is unavailable after the approved feasibility check, implement the authorized-view plus dataset-IAM fallback and retest the raw-dataset denial.
5. Run dbt parse/build, then `python scripts/week9_pii_guard.py --manifest dbt/dataforge/target/manifest.json`, HCL validation/plan, and CI on the exact PR head; record run IDs and outcomes. Review the `customer_id` residual and legal mapping before any real-data use.

Worker G stops after G1–G5/G-PR1 preparation and waits for integrator follow-up; G6–G9 are out of this block.
