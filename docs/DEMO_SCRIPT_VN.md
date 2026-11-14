# Demo 5–7 phút cho mentor — DataForge Week 1–7

**Trạng thái:** kịch bản rehearsal, chưa phải bằng chứng đã thuyết trình hay được mentor sign-off. Dữ liệu commerce là synthetic. Nội dung first-person trong [engineering decisions](ENGINEERING_DECISIONS.md) vẫn cần tác giả review.

| Thời gian | Artifact / màn hình | Lời trình bày gợi ý |
|---|---|---|
| 0:00–0:45 | [README](../README.md), [sơ đồ kiến trúc](architecture/dataforge_overview.drawio) | “DataForge gồm bốn workload riêng: commerce synthetic chạy local, các bài tập batch trên GCP, Spark NYC Taxi chạy local, và Mini3 thời tiết. Đây là portfolio học tập, không phải production service.” |
| 0:45–1:30 | [P6.2 release](releases/v1.0-local.md), [metric contract](metric_contract.md), ảnh Power BI đã lưu | “Order item, payment, return và shipment có grain riêng. Fulfilled sales là proxy metric, không phải doanh thu theo chuẩn kế toán.” |
| 1:30–2:15 | [Week 4 acceptance](cloud/week4_acceptance.md), [Week 5 acceptance](cloud/week5/acceptance_matrix.md) | “Các receipt ghi lại workload cloud giới hạn: GCS/BigQuery staging và change journal với change_seq, immutable manifest, replay. Receipt là lịch sử thực thi, không xác nhận tài nguyên hiện đang chạy.” |
| 2:15–3:00 | [Week 7 acceptance](cloud/week7/acceptance_matrix.md), [failure recovery](cloud/week7/failure_recovery.md) | “Commerce simulator có năm orders và sáu payment events. dbt build kiểm tra candidate rồi guarded publication mới cập nhật Gold. Đây không phải toàn bộ 11 stream của Week 4.” |
| 3:00–3:40 | [Spark benchmark](cloud/week6/benchmark.md) | “Local Spark xử lý 13,069,067 dòng taxi và reconcile output. Broadcast giảm shuffle bytes nhưng median runtime chậm hơn 19.8%; đây là kết quả của workload và host này.” |
| 3:40–4:25 | [Mini3 API-to-Gold receipt](cloud/week7/closure/api_to_gold_e2e_receipt.json), [SCD2 receipt](cloud/week7/closure/dbt_scd2_history_receipt.json) | “Mini3 lấy một ngày đã ổn định cho HCM, HN, DN và ghi ba dòng weather Gold. SCD2 receipt là ba version trạng thái synthetic, không phải customer history.” |
| 4:25–5:20 | [Airflow integration receipt](cloud/week7/closure/airflow_integration_receipt.md), [P7.5 closure](cloud/week7/closure/p75_airflow_correctness.md), [CI evidence](SYLLABUS_COVERAGE.md) | “B PR #9 đã merge tại 9bca18c; D PR #13 merge bình thường tại f4d340ff151557040d85e1688a9e0f94caa2a8c5. D exact-head Week 7 run 43584910006 có tám job thành công và một expected keyless-compile skip; Airflow job 132422133934 qua sáu scenario. Tại snapshot 21:53 +07, merge-SHA base CI 43606510616 và Week 7 run 43606510673 đều passed trên f4d340f; Airflow job 132482197676 succeeded và artifact 14118655954 được lưu. Trước buổi demo hãy đọc checklist mới nhất vì trạng thái remote có thể đổi.” |
| 5:20–6:15 | [Cost table](demo/week7_checkpoint/cost_table.md), [cost/cleanup report](cloud/week7/closure/iam_cost_cleanup.md) | “Khoảng USD 0.095 là gross list-price estimate lịch sử cho Cloud Run và BigQuery, trước free usage và một số dịch vụ chưa định giá; không phải invoice. Actual billed spend, current resource inventory và hourly run-rate chưa xác minh được. Lane D không tạo GCP resource.” |
| 6:15–7:00 | [Syllabus coverage](SYLLABUS_COVERAGE.md), [20 câu hỏi kỹ thuật](demo/week7_checkpoint/technical_defense.md) | “Em phân biệt phần MET, PARTIAL, NOT_RUN và mentor confirmation pending. Các course completion field để trống cho đến khi có xác nhận thật. Phần nào chưa có receipt thì em trình bày là giới hạn.” |

## Trạng thái tích hợp tại thời điểm cập nhật

- B PR #9 merged tại 9bca18c; D PR #13 merged bình thường tại f4d340ff151557040d85e1688a9e0f94caa2a8c5.
- D exact-head PR checks: Week 7 attempt 2 run 43584910006 có 8 job thành công và 1 expected keyless-compile skip; Airflow job 132422133934 qua 6 scenario. Base Postgres job 132417202516 có q10 EXPLAIN plans.
- Lần đầu của D bị timeout ở ngày backfill thứ năm; lần retry không đổi code/assertion đã pass. Task state/root cause chính xác không được bắt lại, nên không tuyên bố đã sửa bằng code.
- Merge-SHA base CI 43606510616 và Week 7 merge-SHA CI 43606510673 passed trên f4d340f; Airflow job 132482197676 succeeded, artifact 14118655954 được lưu.
- H5/R1 inventory chưa hoàn tất: không có GCP resource nào được xác nhận đang chạy, nhưng cũng không thể kết luận inventory rỗng. Actual hourly rate và settled project bill unknown.

Đây là snapshot có thể cũ khi đến ngày demo. Trước khi trình bày, đọc checklist mới nhất và cập nhật CI status. Không chạy cloud job, Terraform operation, notification, hay billed query chỉ để làm mới ảnh.

## Không khẳng định

- Airflow được host trên GCP hoặc chạy unattended theo lịch mỗi ngày.
- Có recurring alert đang bật, actual project bill bằng USD 0, hay budget alert là hard cap.
- Managed Spark batch đã chạy.
- Course, certificate, mentor approval, hay mentor demo đã hoàn thành nếu không có bằng chứng trực tiếp.
- Ảnh chụp màn hình tồn tại khi chỉ có JSON/Markdown receipt.
- AI-assisted first-person decision draft đã được tác giả phê duyệt.
