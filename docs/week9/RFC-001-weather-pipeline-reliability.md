# RFC-001: Reliability layer for the DataForge weather pipeline

**Status:** Draft  ·  **Author:** Tôi, Week 9 integrator  ·  **Date:** 2026-11-18  ·  **Version:** 0.1

## 1. Context and problem

Tôi đang bổ sung reliability layer cho pipeline thời tiết Week 7: Open-Meteo → BigQuery landing → dbt silver/gold → publish có guard. Baseline trên manifest của `origin/main` `6b256f2` có 16 models; 14 có uniqueness/grain check, 14 có description, 12/22 Gold columns có description, và 7/7 sources có freshness. `dbt parse --target offline` đã chạy tại máy; đây chưa phải CI hay live-GCP evidence. Chi tiết ở [baseline](baseline.md).

Ngày 30/10, một calendar-window test chặn publish đúng như thiết kế, nhưng phép so sánh FLOAT64 của test tạo false positive. W7 đã ghi RCA và sửa tolerance; evidence hiện nằm trong W7 PR #40 và chưa thuộc W9 CI. Tôi sẽ dùng sự cố này để chốt một tolerance policy dùng chung, không suy ra rằng gate đã được xác nhận qua W9. [W7 RCA](https://github.com/Dat071104/dataforge-commerce-platform/blob/ead64d9b596f2efa3b87228572cdb7f175b37e2b/docs/cloud/week7/evidence/s4-noop-oct30-rca-20261118.md)

## 2. Goals and non-goals

Goal của tôi là kiểm tra dữ liệu ở producer/consumer boundaries, chặn publish khi có P1, giữ last-good Gold, đo SLO, gửi alert có runbook, và chứng minh gate bằng fault fixtures cùng clean negative control. Tôi cũng muốn CI chạy `dbt build` trên dataset riêng của PR và enforce classification/PII controls bằng code.

Non-goals: sửa vận hành Week 7, tạo real personal data, dựng orchestrator always-on, hoặc mở rộng sang Weeks 10–12.

## 3. SLOs and error budget

| SLI | SLO đề xuất | Cách đo |
|---|---|---|
| Freshness | Gold có ngày D-7 trước 09:30 ICT trong 95% số ngày | `dq_results` và source freshness |
| Completeness | 100% ngày publish có đủ 3/3 province | G1 row count |
| Validity | 100% Gold publish không có blocking failure | G2 dbt tests |
| Latency | p95 pipeline dưới 20 phút | run receipts |
| Alert precision | Ít nhất 95%; F-N0 phải có 0 alert | fault/drill records |

Đây là mục tiêu dự kiến, chưa phải 30 ngày quan sát. Khi error budget hết, tôi đề xuất đóng băng feature PR và chỉ merge reliability fixes.

## 4. Proposed design

G0 kiểm tra payload Open-Meteo trước khi land: field/type, đơn vị, đủ ngày đã request, và trường hợp HTTP 200 nhưng mảng rỗng. G1 kiểm tra landing: schema, 3 province/ngày, uniqueness, domain, range và freshness. G2 dùng dbt tests/contracts cho model grain và biểu thức weather. Mỗi check có một `check_id`, một owner và một fixture lỗi.

Với P1, Write-Audit-Publish chuyển batch vào quarantine kèm reason; publish không đổi và Gold hash phải giữ nguyên. P2 vẫn publish nhưng ghi warning. Mọi gate ghi `dataforge_dq.dq_results`; monitors đọc kết quả này và `INFORMATION_SCHEMA`, không viết lại logic gate. Alert đi qua structured log, log-based metrics, email và Slack webhook; mỗi alert dẫn tới runbook. Chi tiết lỗi nằm trong [failure catalog](failure_modes.md).

## 5. Data contracts and change policy

Tôi dùng ODCS v3.2.0 cho landing, mart và assumptions của Open-Meteo. Structural lint thuộc `datacontract-cli`; dữ liệu thực tế được kiểm bởi G0/G1/G2. Version contract theo SemVer: thay đổi breaking cần major version và consumer acknowledgement; cột nullable mới có thể additive nhưng phải warn và cập nhật schema drift. Các contract đang được soạn tại [`contracts/`](../../contracts/).

## 6. Failure modes and detection

Catalog giữ IDs F01–F15, F-T1 và F-N0 nguyên trạng. P1 như thiếu province, duplicate grain hoặc range sai phải block; F09 replay là NO_OP; F-T1 retry thành công không gửi P1; F-N0 phải có 0 alerts. F13–F15 được kiểm qua throwaway PR fixtures. Baseline hiện có 0 fixture map vào W9 catalog; chưa có fault matrix evidence.

## 7. Privacy and governance

Tôi chỉ dùng synthetic Vietnamese PII, gắn nhãn `data_classification=synthetic`, pseudonymize bằng HMAC ở ingest, giới hạn raw PII vào `restricted_pii`, và chỉ đưa token/giá trị tổng quát vào `pii_safe`. Gold columns cần classification metadata 100%; CI guard phải chặn F13. Project ở `us-central1`: nếu dùng dữ liệu cá nhân thật của người Việt thì đây là cross-border transfer. Mapping điều khoản pháp luật còn chờ xác minh nguồn chính thức; RFC sẽ ghi `LEGAL_UNVERIFIED` nếu không xác nhận được.

## 8. Alternatives considered

Soda Core và GX Core sẽ được đo trên cùng năm checks và cùng slice trước khi chọn G1. OpenMetadata trimmed profile chạy ephemeral trong CI để khớp syllabus; Dataplex/BigQuery lineage là lớp bổ sung, không thay thế catalog. Với F06 tôi chọn block cả ngày thay vì publish 2/3 province vì báo cáo sẽ thiếu một phần population.

## 9. Cost and operations

AF0 giới hạn W9 ở USD 3, stop USD 2.4; AF8 giới hạn lineage ở USD 1, stop USD 0.8. W7 gross envelope hiện khoảng USD 12.89274; cộng W9 cap USD 3 và W8 reserve USD 0.10 là USD 15.99274, sát ngưỡng dừng chung USD 16. Đây là planning envelope, không phải invoice; invoice hiện không có. Tôi sẽ kiểm tra official list price trước mỗi paid action và ghi từng action trong [cost ledger](cost_ledger.md).

## 10. Rollout and rollback

Gate mới chạy `DQ_ENFORCE=warn` trong ba ngày để quan sát false positives, sau đó chuyển sang `block` cho P1. Rollback là `DQ_ENFORCE=warn`; tôi không bỏ assertion để làm CI xanh. Mọi drill chỉ ghi lên `w9_drill` hoặc `dbt_ci_pr_<n>`.

## 11. Risks and open questions

Rủi ro lớn nhất là chi phí còn headroom rất nhỏ theo cumulative stop line, false positives do FLOAT64, và thiếu Slack webhook cho đến khi người dùng hoàn tất H-W9-1. Tôi cần mentor quyết định có giữ 30-day SLOs như hiện tại hay chỉnh sau khi đủ observed data; tôi cũng cần xác nhận cách gọi nghĩa vụ cross-border sau khi kiểm tra văn bản pháp luật đang hiệu lực.

## Appendix: evidence and decision log

- [Baseline](baseline.md) — local offline dbt parse; not CI/live-GCP.
- [Failure catalog](failure_modes.md) — planned detector map; fixtures pending.
- [Tool ADR](adr_quality_tooling.md) — D-2 pending paired spike.
- Contracts: [`weather_landing.v1.yaml`](../../contracts/weather_landing.v1.yaml), [`mart_weather_province_daily.v1.yaml`](../../contracts/mart_weather_province_daily.v1.yaml), [`open_meteo_api.assumptions.yaml`](../../contracts/open_meteo_api.assumptions.yaml).
- [Cost ledger](cost_ledger.md) — no W9 paid action recorded yet.

Decision log: No mentor comments received. Status remains Draft; only the mentor may move it beyond In review.
