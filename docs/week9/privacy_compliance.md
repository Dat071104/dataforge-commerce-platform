# W9 privacy compliance map (synthetic PII demo)

**Scope.** Week 9 processes only synthetic Vietnamese customer profiles (`data_classification=synthetic`, reserved CCCD prefix `999`, `example.com` e-mails, `+84-000-` phones). No real personal data is collected. This page maps the obligations a real deployment would face to the technical controls built in W9, so a mentor can judge the design. It is not legal advice.

## 1. Which legal texts apply (checked 2026-11-21)

| Text | Status on 2026-11-21 | Source |
|---|---|---|
| Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15 | In force from 01/01/2026 | [Công báo](https://congbao.chinhphu.vn/van-ban/luat-so-91-2025-qh15-45578.htm), [Bộ Công an](https://www.bocongan.gov.vn/bai-viet/luat-bao-ve-du-lieu-ca-nhan-chinh-thuc-co-hieu-luc-thi-hanh-tu-ngay-01-01-2026-1767186124) |
| Nghị định 356/2025/NĐ-CP (detailing the Law) | In force from 01/01/2026 | [LuatVietnam summary](https://luatvietnam.vn/linh-vuc-khac/luat-bao-ve-du-lieu-ca-nhan-moi-nhat-va-van-ban-huong-dan-883-106497-article.html) |
| Nghị định 13/2023/NĐ-CP (named in the syllabus) | **No longer in force** from 01/01/2026; replaced by NĐ 356/2025 | [LuatVietnam summary](https://luatvietnam.vn/linh-vuc-khac/luat-bao-ve-du-lieu-ca-nhan-moi-nhat-va-van-ban-huong-dan-883-106497-article.html) |

The syllabus cites NĐ 13/2023. This RFC therefore maps controls to the Law 91/2025 and NĐ 356/2025 regime and mentions NĐ 13/2023 only as history. **Article numbers are `LEGAL_UNVERIFIED`:** the official text was not read article by article in this session, and secondary summaries disagree on details. Before the RFC is Accepted, the article references below must be checked against the Công báo text and quoted verbatim.

## 2. Obligation → control → evidence

| Obligation (concept) | Technical control in W9 | Evidence | Status |
|---|---|---|---|
| Lawful basis / consent; purpose limitation | Every column declares `purpose` and `retention_days` in `governance/classification.yml` and dbt `meta`; CI fails if any Gold column is unclassified | `scripts/week9_classification_coverage.py` (351/351 columns, 55/55 Gold); test `G1-CLASSIFICATION-001` | Control built; consent capture itself is out of scope (synthetic data) |
| Data minimisation | Public/analyst mart holds only `customer_token` (HMAC), `age_band`, `province_id`, `email_masked` | `pii_safe.dim_customer_profile_safe` schema; G4 `safe_table_raw_columns_absent=true` | PASS (G4, 2026-11-21) |
| Basic vs sensitive data classification | Four classes Public / Internal / Confidential / Restricted; identity, e-mail, phone and birth date carry BigQuery policy tags | Policy tags on `restricted_pii.customer_profile` (5 tagged columns) | PASS |
| Security measures (access control, pseudonymisation) | HMAC-SHA256 at ingest with the key in Secret Manager; raw data only in `restricted_pii`; policy tags + data-masking policies; IAM tested both ways | `docs/week9/evidence/g3-g4-pii-proof-20261121.md`: analyst denied raw, privileged reads raw, CI SA denied by policy tag | PASS |
| Leak prevention in change management | CI PII-leak guard on `manifest.json` fails any public model with a direct-PII column | Fixture PR F13 (#54) | See fault-matrix evidence |
| Data-subject rights (access, deletion) | Token join lets one subject be located across layers; deletion drill (P2) through raw, staging, mart and SCD2 snapshot is designed; BigQuery time travel (2–7 days) and 7-day fail-safe limit true erasure; crypto-shredding (per-subject AEAD keyset) proposed | `scripts/week9_pii_erasure.py` (G-lane); RFC §7 | Designed; live drill not run |
| Impact assessment (DPIA-lite) | This page + RFC §7 + failure catalog F13 | — | Draft |
| Breach notification (deadline under Law 91/2025 is `LEGAL_UNVERIFIED`; the syllabus-era NĐ 13/2023 used 72 h) | P1 alert path (log metric → Monitoring email + Slack) with runbooks; a real breach runbook must add the regulator notification step | `docs/week9/runbooks/`, live drill H-W9-3 | Partial: technical alerting only |
| Cross-border transfer | Project `dataforge-p7-lab-d0f725` stores data in `us-central1`. For real Vietnamese personal data this is a transfer abroad that needs the transfer impact dossier required by the Law and decree | RFC §7 open question | **Not compliant for real data**; acceptable only because data is synthetic |
| Retention | `retention_days` per column; PR datasets expire in 24 h, `w9_drill` tables in 7 days | Terraform `datasets.tf` | Partial: no automated deletion for `restricted_pii` |

## 3. Open questions for the mentor

1. Should a real deployment move PII storage to a Vietnam-hosted region, or keep `us-central1` with a transfer impact dossier?
2. Is HMAC tokenisation enough as pseudonymisation for the mart, or must the key be rotated on a schedule?
3. Which article of Law 91/2025 should the breach runbook quote for the notification deadline (`LEGAL_UNVERIFIED`)?
