# RFC-001: Reliability layer for the DataForge weather pipeline

**Status:** In review  ·  **Author:** Week 9 integrator  ·  **Reviewers:** mentor (H-W9-2), RFC reviewer persona  ·  **Date:** 2026-11-21  ·  **Version:** 0.2

## 1. Context and problem

Pipeline thời tiết Week 7 (Open-Meteo → BigQuery landing → dbt silver/gold → publish) đã chạy được, nhưng trước W9 chưa có lớp nào chứng minh dữ liệu đúng trước khi publish. Baseline trên manifest `6b256f2`: 16 models, 14 có uniqueness/grain check, 12/22 cột Gold có description, 7/7 sources có freshness, **0 fault fixture** ([baseline](baseline.md)). CI không chạy `dbt build` thật trên PR, không có data contract machine-readable, không có alert chất lượng dữ liệu, không có catalog/lineage.

Một sự cố thật cho thấy cái giá của gate sai. Ngày 30/10 một test calendar-window chặn publish đúng thiết kế, nhưng do so sánh FLOAT64 bằng `=` nên đó là false positive ([postmortem-000](postmortem-000.md)). Gate đã làm đúng việc, còn test thì sai. RFC này đặt quy tắc tolerance chung và yêu cầu mỗi check phải có fixture chứng minh nó fail được.

## 2. Goals and non-goals

**Goals:** kiểm tra dữ liệu ở boundary producer/consumer; chặn publish khi có P1 và giữ Gold last-good; đo SLO; alert có runbook; chứng minh mọi check bằng fault fixture cùng một negative control sạch; CI build thật trên dataset riêng của PR; enforce phân loại và che PII bằng code.

**Non-goals:** sửa vận hành Week 7; dùng dữ liệu cá nhân thật; dựng orchestrator chạy thường trực; Weeks 10–12.

## 3. SLOs and error budget

| SLI | SLO đề xuất (30 ngày) | Đo bằng |
|---|---|---|
| Freshness | Gold có ngày D-7 trước 09:30 ICT trong 95% số ngày | `dq_results`, dbt source freshness |
| Completeness | 100% ngày publish có đủ 3/3 province | `G1.LANDING.ROWS_PER_DATE` |
| Validity | 100% Gold đã publish không có blocking failure | G2 dbt tests (`tier_blocking`) |
| Latency | p95 pipeline < 20 phút | run receipts |
| Alert precision | ≥ 95%; F-N0 phải ra 0 alert | fault matrix + drill |

Đây là con số **dự kiến**; W9 không có 30 ngày quan sát. Hết error budget thì đóng băng PR tính năng, chỉ merge PR reliability.

## 4. Proposed design

```
Open-Meteo ─► G0 ingest contract ─► landing ─► G1 boundary gate (GX Core) ─► dbt build (candidate)
                                     │ fail                                    ─► G2 dbt tests + model contracts
                                     ▼                                         ─► publish (WAP) ─► Gold ─► Power BI / W10
                              quarantine/<run_id>/ (Gold giữ last-good, hash không đổi)
mọi gate ─► dataforge_dq.dq_results ─► monitors ─► Cloud Logging (DQ_GATE_FAILED…) ─► log metric ─► alert policy ─► email
                                                                                  └► Slack webhook (Secret Manager) + runbook link
```

- **G0** (Python ingest): field/type, đơn vị, đủ số ngày đã request, HTTP 200 nhưng rỗng (F05a, F11).
- **G1** (GX Core 1.25.0, `python -m dataforge.dq gate`): schema, 3 province/ngày, null/duplicate/domain, range vật lý, ngày tương lai, đơn vị °F. Cờ `DQ_ENFORCE=warn|block`.
- **G2** (dbt): PK/grain, expression test F10, model contract trên mart, source freshness F07 (36 h warn / 72 h error).
- **WAP**: P1 → quarantine kèm lý do, Gold không đổi (assert hash). P2 vẫn publish và cảnh báo.
- **Observability**: `dq_results` là nguồn sự thật duy nhất; monitor chỉ đọc kết quả mới nhất cho mỗi (check, ngày) (R-16) và metadata `INFORMATION_SCHEMA`, không chạy lại logic gate.
- **Gate không phụ thuộc orchestrator**: CLI gọi được từ Airflow (`quality_gate_landing` trước `dbt_weather_build`), GitHub Actions hoặc tay.

## 5. Data contracts and change policy

ODCS v3.2.0 cho `weather_landing`, `mart_weather_province_daily` và các giả định về Open-Meteo ([`contracts/`](../../contracts/)). `datacontract lint` và `datacontract breaking --perspective consumer` (so với `origin/main`) chạy trên mỗi PR. SemVer: breaking change (xoá/đổi type cột, đổi grain, đổi ngữ nghĩa window) cần major version và consumer acknowledgement; thêm cột nullable là additive nhưng phải cảnh báo P2. Fixture F14 (#55) chứng minh CI chặn việc xoá cột `temp_max_c` khỏi contract.

## 6. Failure modes and detection

Catalog đầy đủ ở [failure_modes.md](failure_modes.md); evidence ở [fault_matrix.md](evidence/fault_matrix.md).

- F01–F06, F08, F11, F12: block đúng `check_id`, Gold hash không đổi (CI fixture, run `44867546904`).
- F05b: publish + P2 warn. F09: NO_OP, 0 alert. F-T1: retry thành công, 0 P1. F-N0: 0 alert.
- F07/F10 chạy trên BigQuery cô lập (`w9_drill`); F13–F15 là PR fixture dùng một lần.
- Live drill F06 (H-W9-3): alert thật tới email và Slack, MTTD đo được ([drill](evidence/h-w9-3-f06-live-drill.md)).

## 7. Privacy and governance

- Dữ liệu PII **chỉ là synthetic** (`data_classification=synthetic`); raw nằm trong `restricted_pii`, mart `pii_safe` chỉ có token HMAC-SHA256 (khoá trong Secret Manager), `age_band`, `province_id`, `email_masked`.
- 5 cột raw có BigQuery policy tag (identity, email, phone, birth_date) và data-masking policy. Kiểm tra truy cập cả hai chiều PASS: analyst đọc mart, bị từ chối raw; privileged đọc raw; CI SA bị `DENIED_BY_POLICY_TAG` ([evidence](evidence/g3-g4-pii-proof-20261121.md)).
- 351/351 cột (55/55 cột Gold) có `classification`, `pii_type`, `purpose`, `retention_days`; PII-leak guard đọc `manifest.json` chặn cột PII trực tiếp trong model public (F13).
- Catalog: OpenMetadata 2.0.7 chạy ephemeral trong CI (dbt manifest ingest 11 records, 0 lỗi); lineage GCP-native qua Data Lineage API: weather 5 links, PII 2 links `customer_profile → customer_profile_restricted / dim_customer_profile_safe`. API đã tắt sau khi có evidence.
- **Pháp lý:** NĐ 13/2023 trong syllabus đã hết hiệu lực từ 01/01/2026; khung hiện hành là Luật 91/2025/QH15 và NĐ 356/2025/NĐ-CP. Số điều cụ thể còn `LEGAL_UNVERIFIED` ([privacy_compliance.md](privacy_compliance.md)).
- **Cross-border:** project ở `us-central1`. Với dữ liệu thật của người Việt, đây là chuyển dữ liệu ra nước ngoài và cần hồ sơ đánh giá tác động; thiết kế hiện tại chỉ chấp nhận được vì dữ liệu là synthetic.

## 8. Alternatives considered

| Quyết định | Đã chọn | Phương án còn lại và lý do không chọn |
|---|---|---|
| Boundary gate | GX Core 1.25.0 (Apache-2.0) | Soda Core v4: license ELv2/proprietary, có lỗi với schema/group_by trong spike ([ADR](adr_quality_tooling.md)) |
| Catalog | OpenMetadata trimmed profile, ephemeral trong CI + Dataplex lineage | DataHub: cần ~8 GB RAM và Kafka; Dataplex một mình không hiển thị dbt tests/descriptions |
| Thiếu 1/3 province | Chặn cả ngày | Publish 2/3 kèm cờ: Power BI so sánh 3 tỉnh, publish thiếu dễ đọc sai |
| Orchestrator sau teardown VM | Gate là CLI, drill chạy từ GitHub Actions / tay | Cloud Workflows: chỉ cần nếu mentor muốn chạy live hằng ngày |
| Slack | Webhook từ runner (message có context, dedup theo (check, ngày)) | Monitoring native Slack channel: cần OAuth trên console, ít context |

## 9. Cost and operations

Cap W9 USD 3 (dừng ở 2.4), lineage USD 1 (dừng ở 0.8). Ước tính gross đã biết khoảng USD 0.018; forecast khoảng USD 0.36 ([cost ledger](cost_ledger.md)). Chưa có invoice/SKU nên con số thật được ghi `UNVERIFIED`. Vận hành: mỗi alert dẫn tới một runbook ([runbooks/](runbooks/)); dead-man's switch bị tắt ngoài drill vì VM W7 đã teardown, tránh alert fatigue.

## 10. Rollout and rollback

Gate mới chạy `DQ_ENFORCE=warn` (shadow) ba ngày để đo false positive, sau đó chuyển `block` cho P1. Rollback là `DQ_ENFORCE=warn`; không bao giờ xoá assertion để làm CI xanh. Drill chỉ ghi vào `w9_drill` hoặc `dbt_ci_pr_<n>`; dataset PR tự xoá khi PR đóng và có TTL 24 h làm lưới an toàn.

## 11. Risks and open questions

1. Giữ SLO 30 ngày như đề xuất hay điều chỉnh sau khi có đủ dữ liệu quan sát?
2. Dữ liệu thật: chuyển PII sang region Việt Nam, hay giữ `us-central1` kèm hồ sơ chuyển dữ liệu ra nước ngoài?
3. Có cần rotate khoá HMAC theo lịch không, và khi rotate thì token cũ được xử lý thế nào?
4. Ai được duyệt release quarantine (`quarantine-release.md`): data owner hay on-call?
5. Mentor xác nhận cách trích dẫn Luật 91/2025 / NĐ 356/2025 (`LEGAL_UNVERIFIED`).

## Appendix A: incidents found while building W9 (root cause → fix)

| # | Triệu chứng | Root cause | Fix |
|---|---|---|---|
| R-1…R-8 | xem `15_W9_SPEC_P2.md` | jq `-r`, `bq show --location`, pandas/BigQuery dtypes, Airflow wiring/race, slim-CI unit tests, billed-bytes JSON path, yamllint | `896f536` … `9f51074` |
| R-9 | PII proof: `setCategory` denied | gắn policy tag cần thêm `datacatalog.taxonomies.get` + maskedReader cho mart | AF2-ext-2b IAM (đã gỡ sau G4) |
| R-10 | OpenMetadata `no-auth` bị từ chối | OM 2.0.7 bỏ provider `no-auth` | basic auth + JWT bot (`5ab2f43`) |
| R-11 | policy tag trên view | BigQuery không lưu policy tag trên cột view | `persist_docs.columns=false` cho view (`78e0025`) |
| R-14 | PII proof `RunCostGuardError` | hook `on-run-end` nằm trong `run_results.json` mà không có job ID | bỏ qua hook không có job (`02812e6`) |
| R-15 | Airflow harness `results=[]` (flaky) | đọc log trước khi supervisor flush | poll tối đa 60 s (`554c54f`) |
| R-16 | (phát hiện trước drill) FAIL cũ bị gửi lại sau khi đã RESOLVED | monitor đọc mọi dòng trong ngày | chỉ giữ kết quả mới nhất cho mỗi (check, ngày) (`2fdf638`) |
| R-17 | slim CI fail khi PR sửa mart | state manifest parse bằng target offline giả, nên `--defer` không bao giờ tới prod | target `prod_state` + `--favor-state` (`f2a11f2`) |
| R-18 | F07/F10 live `UNVERIFIED` | parquet `timestamp[ns]` → INT64 trong BigQuery | đổi sang µs trước khi load (`fed8ea9`) |
| T3 | Terraform plan 6/1/0 | drift: đổi event WIF sang `pull_request_target` đã merge nhưng chưa apply | apply có duyệt (AF2-ext-2c) |

## Appendix B: evidence index

- [fault_matrix.md](evidence/fault_matrix.md) · [g3-g4-pii-proof-20261121.md](evidence/g3-g4-pii-proof-20261121.md) · [g7-lineage-w9-drill.md](evidence/g7-lineage-w9-drill.md) · [h-w9-3-f06-live-drill.md](evidence/h-w9-3-f06-live-drill.md)
- [postmortem-000.md](postmortem-000.md) (Oct30 false positive) · [postmortem-001.md](postmortem-001.md) (game day)
- [privacy_compliance.md](privacy_compliance.md) · [adr_quality_tooling.md](adr_quality_tooling.md) · [cost_ledger.md](cost_ledger.md) · contracts trong [`contracts/`](../../contracts/)

## Decision log

| # | Comment (nguồn) | Quyết định | Lý do |
|---|---|---|---|
| — | Chưa có comment của mentor | — | Trạng thái giữ ở In review; chỉ mentor được chuyển sang Accepted (H-W9-2). |
