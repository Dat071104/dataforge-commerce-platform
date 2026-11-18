---
name: dataforge-governance-pii
description: Classify DataForge columns, generate synthetic Vietnamese PII, pseudonymize and mask it, enforce BigQuery policy tags and PII-leak checks, capture catalog lineage, and map controls to Vietnamese personal-data law.
---

# Governance and PII (Week 9)

1. **Synthetic only.** Generate with a fixed seed and label `data_classification=synthetic`. Use identifiers that cannot belong to a real person: CCCD prefix `999` (not a province code), e-mails `@example.com`, and a phone prefix that you document as not allocated. Never load, scrape or paste real personal data.
2. Every column in sources and models declares `meta: {classification: public|internal|confidential|restricted, pii_type, purpose, retention_days}`. Gold coverage must be 100%.
3. Pseudonymize in Python at ingest with HMAC-SHA256. The key comes from Secret Manager `w9-pii-hmac-key`. Never put keys or salts in SQL text: query text is stored in `INFORMATION_SCHEMA.JOBS`. Raw PII lands only in `restricted_pii`.
4. Warehouse enforcement: policy-tag taxonomy + data masking on `restricted_pii`, and dbt `policy_tags` with column-level `persist_docs`. Run a feasibility spike first. If masking is unavailable on this project, fall back to authorized views + dataset IAM and record why.
5. Marts (`pii_safe`) expose only tokens or generalized values (age band, province, masked e-mail).
6. Prove access with tests: the analyst test SA sees masked values, the privileged test SA sees raw values, and the analyst is denied the raw dataset (positive + negative), reusing the `scripts/week7_verify_iam.py` pattern. Never grant the test SAs anything else.
7. `scripts/week9_pii_guard.py` fails a PR when a PII column reaches a non-restricted model without a mask macro. Keep its failing fixture (F13).
8. Legal mapping: cite only official text (vbpl.vn, chinhphu.vn, congbao.chinhphu.vn) with a link and the exact article. Check which provisions of NĐ 13/2023/NĐ-CP still apply now that the Personal Data Protection Law 91/2025/QH15 is in force (from 2026-01-01). If you cannot open the source, mark the citation `LEGAL_UNVERIFIED`. Always state that the project region `us-central1` means real Vietnamese personal data would be a cross-border transfer.
9. Lineage: OpenMetadata in a trimmed profile (server + Postgres + OpenSearch, CLI ingestion, GitHub Actions only), plus Dataplex/BigQuery lineage time-boxed per Addendum F row AF8. The integrator disables the Lineage API after the evidence is captured.
