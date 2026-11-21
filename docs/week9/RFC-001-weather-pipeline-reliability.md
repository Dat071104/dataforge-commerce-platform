# RFC-001: Reliability layer for the DataForge weather pipeline

**Status:** In review  ·  **Author:** Week 9 integrator  ·  **Reviewers:** mentor (H-W9-2); RFC reviewer persona (pre-review, verdict Revise → addressed in v0.3)  ·  **Date:** 2026-11-21  ·  **Version:** 0.3

## 1. Context and problem

Pipeline thời tiết W7 (Open-Meteo → BigQuery landing → dbt silver/gold → publish) chạy được, nhưng trước W9 không có lớp nào chứng minh dữ liệu đúng trước khi publish. Baseline `6b256f2`: 12/22 cột Gold có description, 0 fault fixture, CI không `dbt build` trên PR, không có alert chất lượng dữ liệu ([baseline](baseline.md)).

Sự cố thật: ngày 17/11, khi replay ngày quan sát 30/10, test calendar-window (P1) chặn publish. Gate làm đúng, nhưng test sai: nó so FLOAT64 bằng `=` (`30.2` khác `30.199999999999996`). Đã sửa ở PR #39 (`a160f8b`) ([postmortem-000](postmortem-000.md)). Bài học dẫn tới quy tắc so sánh số ở §5 và yêu cầu mỗi check phải có fixture chứng minh nó fail được.

## 2. Goals and non-goals

**Goals:** chặn P1 trước khi publish và giữ Gold last-good; contract ở boundary; alert có runbook; mọi check có fault fixture cùng một negative control; CI build thật trên dataset riêng của PR; enforce phân loại/che PII bằng code.
**Non-goals:** bật cho production trong W9 (gate chỉ chấp nhận `w9_drill`/`dbt_ci_pr_*`); dữ liệu cá nhân thật; orchestrator chạy thường trực.

## 3. SLO (chỉ có hiệu lực khi đã có lịch chạy production)

Một SLI hướng tới consumer: **Gold của ngày D-7 được publish, với mọi check blocking PASS, trước 09:30 ICT** — mục tiêu 95% số ngày/30 ngày (budget khoảng 1,5 ngày). Hết budget thì đóng băng PR tính năng. Cần thêm một check freshness lúc 10:00 ICT khớp SLO; alert freshness hiện tại (36 h P2 / 72 h P1) chậm hơn SLO 1,5–3 ngày. Latency p95 và alert precision chỉ được báo cáo dưới dạng chỉ số, chưa thành SLO cho tới khi có ≥ 20 mẫu.

## 4. Design

G0 (ingest contract, Python) → landing → **G1** (GX Core 1.25.0: schema, 3 tỉnh/ngày, null/duplicate/domain, range, ngày tương lai, °F) → dbt candidate → **G2** (grain, F10, model contract, source freshness) → publish (WAP). P1 thì chặn, đưa vào quarantine và giữ hash Gold; P2 vẫn publish kèm cảnh báo. Mọi gate ghi `dataforge_dq.dq_results`. Monitor chỉ đọc kết quả mới nhất cho mỗi (check, ngày) sau một watermark `--since`; nó không tự đánh giá lại check.

**Alert:** monitor ghi **mọi** event vào Cloud Logging trước, rồi mới route Slack. Lỗi Slack sinh event P1 `ALERTING.DELIVERY_FAILED`, đi email (fixture F-A1). Email đi qua log metric → 3 policy P1 (gate, volume, schema): một incident cho mỗi policy, `auto_close` 1 h, nên lỗi P1 thứ hai cùng loại trong 1 giờ sẽ không ra email mới; nội dung chi tiết nằm ở Slack. Slack dedup theo (check, ngày) và gửi RESOLVED khi check PASS lại.

**Phạm vi đã chứng minh:** chỉ trên dataset cô lập. Đưa vào production (allowlist dataset, adapter Airflow `quality_gate_landing`, lịch chạy monitor) là việc follow-up.

## 5. Contracts and numeric rule

ODCS v3.2.0 cho landing, mart và Open-Meteo; mỗi PR chạy `datacontract lint` và `breaking --perspective consumer` so với `main` (F14 chứng minh). SemVer: breaking cần major version và consumer ack; cột nullable mới là P2.
**Quy tắc so sánh số:** không so FLOAT64 bằng `=`. Dùng macro `dq_float_equal` (dung sai tuyệt đối, mặc định 1e-6 cho giá trị đo; 1e-12 cho phép tính tái lập), giữ NULL parity. Data diff của CI phải theo cùng quy tắc (action item A3).

## 6. Failure modes and evidence

Chi tiết ở [fault_matrix.md](evidence/fault_matrix.md) và [failure_modes.md](failure_modes.md).

| Nhóm | Kết quả | Mức evidence / ghi chú |
|---|---|---|
| F01–F06, F08, F11, F12, F05b, F09, F-T1, F-N0 | PASS | CI fixture (run `44867546904`); hash Gold không đổi |
| F07, F10 | PASS | CI-live BigQuery (runs `44872770442`, `44873779562`); hash slice Gold rỗng nên chưa chứng minh "Gold không đổi" (A4) |
| F13 | Bị chặn | CI chặn ở test registry (56≠55) trước bước guard; PII guard chỉ được chứng minh local (exit 1) |
| F14 | PASS | `datacontract breaking` đỏ (job `136744399247`) |
| F15 | PASS | data diff `prod_only=6`, `ci_only=6` (run `44882607355`, sau khi merge fix R-17/R-19/R-21 trong #57) |
| F-A1 Slack outage | PASS | unit fixture |
| F-N0 live (precision) | PASS | 13:20: 12 event đều PASS, 0 alert |
| Live drill F06 (H-W9-3) | PASS | block 26 s, event 58 s, Slack ≤ 98 s, email nhận được (chưa đo giờ); MTTR 1 phút 58 giây ([drill](evidence/h-w9-3-f06-live-drill.md)) |

Chưa có fixture (rủi ro được chấp nhận, xem §11): pipeline không chạy (dead-man switch đang tắt), upstream sửa giá trị lịch sử, trùng lặp xuyên request, giá trị "kẹt"/lặp lại.

## 7. Privacy and governance

Chỉ dùng PII synthetic. Raw nằm trong `restricted_pii` với 5 cột gắn policy tag và masking; mart `pii_safe` chỉ có token HMAC, `age_band`, tỉnh, email đã mask. Kiểm tra truy cập 2 chiều PASS ([evidence](evidence/g3-g4-pii-proof-20261121.md): run `44866987378`). 351/351 cột có classification. Catalog: OpenMetadata ephemeral trong CI (run `44864861534`, dbt manifest 11 records/0 lỗi). Lineage GCP: weather 5 link; PII 2 link ([JSON](evidence/g7-pii-lineage-20261121.json)); API tắt lúc 11:54:50.
**Pháp lý:** Luật 91/2025/QH15 (Điều 20: chuyển dữ liệu ra nước ngoài; Điều 39: chuyển tiếp) và NĐ 356/2025 (Điều 42 khoản 2: bãi bỏ NĐ 13/2023), trích từ văn bản chính thức ([map](privacy_compliance.md)). Project ở `us-central1` nên dữ liệu thật sẽ thuộc trường hợp Điều 20. Chưa làm: drill xoá dữ liệu (bị giới hạn bởi time travel + fail-safe 7 ngày; crypto-shredding mới đề xuất), retention tự động cho `restricted_pii`, bước thông báo cơ quan quản lý trong runbook vi phạm (hạn chót `LEGAL_UNVERIFIED`).

## 8. Alternatives

| Quyết định | Chọn | Không chọn, vì |
|---|---|---|
| Gate | GX Core (Apache-2.0) | Soda v4: ELv2, lỗi schema/group_by ([ADR](adr_quality_tooling.md)) |
| Catalog | OpenMetadata trong CI + Dataplex lineage | DataHub: ~8 GB RAM + Kafka |
| Thiếu 1/3 tỉnh | Chặn cả ngày | Publish 2/3: dashboard so sánh 3 tỉnh sẽ đọc sai |
| Tin cậy CI cloud | `pull_request_target` + kiểm same-repo/head-SHA + `W9_WIF_PR_TARGET_ENABLED` | `pull_request`: code của PR head xin được token WIF |
| Slack | Webhook từ runner | Kênh Slack của Monitoring: cần OAuth, ít context |

## 9. Cost

Cap W9 USD 3 (dừng ở 2.4), lineage USD 1. Gross ước tính tới 13:00 khoảng USD 0.026; forecast khoảng USD 0.37 ([ledger](cost_ledger.md); chưa có invoice). Ngưỡng dừng chung W7+W8+W9 là USD 16; forecast hiện tại khoảng USD 13.36, còn dư khoảng USD 2.6. Chi phí chạy: một PR build 40–700 MiB (≈ USD 0.0003–0.004); mỗi lần chạy monitor vài job 10 MiB; chi phí định kỳ gồm 2 version Secret Manager và ingest log metric.

## 10. Rollout and rollback

Shadow (`warn`) cho tới khi có ≥ 10 lần chạy sạch liên tiếp, gồm F-N0, với 0 false positive P1; sau đó `block`. CLI mặc định là `block` (fail-closed). **Rollback theo từng check, không bật/tắt toàn cục:** một override được review (check_id, hạ xuống P2, owner, hết hạn ≤ 7 ngày) và được ghi vào `dq_results` (A2). Hành động mặc định khi có sự cố là giữ không publish và giữ last-good. `DQ_ENFORCE=warn` không phải cách xử lý sự cố, như runbook đã ghi.

## 11. Risks and open questions

Rủi ro chấp nhận (có owner): dead-man switch đang tắt sau teardown VM; chưa có fixture cho upstream revision, trùng lặp xuyên request, giá trị kẹt; email gộp theo policy. Câu hỏi cho mentor:
1. SLO ở §3 có hợp lý không?
2. Dữ liệu thật: chuyển sang region VN hay giữ `us-central1` kèm hồ sơ theo Điều 20?
3. Chính sách rotate khoá HMAC?
4. Ai được duyệt override/release quarantine?
5. Hạn chót thông báo vi phạm theo Luật 91.

## Appendix A: incidents that changed the design

| # | Root cause → change |
|---|---|
| R-16 | Monitor gửi lại FAIL cũ sau khi đã RESOLVED → chỉ lấy kết quả mới nhất cho mỗi (check, ngày) |
| R-17 | State manifest parse bằng target offline giả nên `--defer` không tới được prod → target `prod_state` + `--favor-state` |
| R-18 | Parquet `timestamp[ns]` thành INT64 trong BigQuery → đổi sang µs trước khi load |
| R-19 | Container không nhận `GITHUB_RUN_ID` → guard 5 GiB của run fail-closed → truyền biến vào |
| R-20 | Gate-test ghi lỗi tiêm vào `dq_results` → tắt ghi kết quả + watermark `--since` |
| R-21 | Concurrency group chung huỷ run đang chờ → group theo event + PR |
| R-22 | `ready_for_review` lúc merge: build chạy song song với cleanup và tạo lại `dbt_ci_pr_57` sau khi đã xoá → xoá tay ở AF12; action A8 |
| F-A1 | Slack lỗi chặn luôn việc log, mất email → log trước, route sau |
| T3 | Drift WIF (`38b08a9` chưa apply) → apply có duyệt (AF2-ext-2c) |

R-1…R-15 (lỗi build/CI không đổi thiết kế) nằm trong `failure_modes.md` và PR log.

## Appendix B: action items

A1 check freshness 10:00 ICT · A2 cơ chế override theo check · A3 data diff dùng dung sai và trở thành check bắt buộc có review · A4 hash Gold không rỗng cho F07/F10 · A5 đưa test đếm cột registry ra sau PII guard · A6 fixture cho stuck-value và upstream revision · A7 bước thông báo cơ quan quản lý trong runbook vi phạm · A8 job build bỏ qua khi PR đã đóng/merge, và cleanup chờ build cùng PR xong (R-22).

## Decision log (pre-review, 2026-11-21)

| # | Comment | Quyết định |
|---|---|---|
| 1 | Claim "đã xong" khi chưa có evidence | Accepted: F15 ghi PENDING (PASS sau đó, run `44882607355`); drill chỉ ghi PASS sau khi có evidence; thêm evidence lineage PII + bản ghi tắt API; commit postmortem-000; sửa ngày sự cố |
| 2 | Fault matrix bị tóm thành PASS chung | Accepted: thêm cột mức evidence/ghi chú (§6); bổ sung R-19 |
| 3 | Rollback `warn` mâu thuẫn runbook; mặc định fail-open | Accepted: rollback theo check (A2), CLI mặc định `block` (`ddc4078`), shadow kết thúc theo số lần chạy |
| 4 | SLO không đo được | Accepted: một SLI consumer, chỉ hiệu lực khi có lịch chạy; A1 |
| 5 | Lỗi Slack chặn email; dedup | Accepted: log trước, route sau, event DELIVERY_FAILED (`a1f224d`); ghi rõ cơ chế gộp email (§4) |
| 6 | Thiếu failure mode | Partly: F-A1 thêm; các mục còn lại là rủi ro chấp nhận (§11, A6) |
| 7 | Quy tắc dung sai, data diff dùng `=` | Accepted: §5; A3 |
| 8 | Trích dẫn pháp lý không nhất quán | Accepted: dùng Điều 20/39 và NĐ 356 Điều 42(2) từ nguồn chính thức |
| 9 | Sơ đồ ngầm hiểu đã chạy production | Accepted: thêm dòng phạm vi (§4) |
| 10 | Chi phí | Accepted: cập nhật số, ngưỡng dừng chung, chi phí chạy (§9) |
| 11 | Quyết định tin cậy CI | Accepted: thêm dòng `pull_request_target` (§8) |
| 12 | Độ dài | Accepted: rút gọn Appendix A; phần thân khoảng 2 trang |
