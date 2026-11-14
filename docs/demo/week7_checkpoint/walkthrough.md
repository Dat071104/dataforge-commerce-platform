# Mentor walkthrough · 7 minutes

This is a rehearsal script, not evidence that a presentation or mentor sign-off occurred. Use repository receipts and the latest integrator checklist as the source of truth. Keep the demo read-only: do not start jobs, create cloud resources, send alerts, or run billed BigQuery queries.

| Time | Màn hình / artifact | Lời trình bày gợi ý |
|---|---|---|
| 0:00–0:45 | [README](../../../README.md), [sơ đồ kiến trúc](../../architecture/dataforge_overview.drawio) | “DataForge gồm bốn workload có ranh giới riêng: commerce tổng hợp chạy local, bài tập GCP theo từng giai đoạn, Spark NYC Taxi chạy local, và Mini3 thời tiết. Đây là portfolio học tập, không phải production service.” |
| 0:45–1:30 | [P6.2 report](../../releases/v1.0-local.md), [metric contract](../../metric_contract.md), ảnh Power BI đã lưu | “Order item, payment, return và shipment có grain riêng. Fulfilled sales là proxy metric, không phải doanh thu theo chuẩn kế toán. Dữ liệu commerce là synthetic.” |
| 1:30–2:15 | [Week 4 acceptance](../../cloud/week4_acceptance.md), [Week 5 acceptance](../../cloud/week5/acceptance_matrix.md) | “Week 4 ghi nhận một lần chuyển dữ liệu tổng hợp qua GCS/BigQuery. Week 5 là simulator riêng dùng change_seq, manifest bất biến và replay. Các receipt là lịch sử của workload giới hạn, không phải trạng thái cloud hiện tại.” |
| 2:15–3:00 | [Week 7 acceptance](../../cloud/week7/acceptance_matrix.md), [recovery report](../../cloud/week7/failure_recovery.md) | “Week 7 commerce dùng năm orders và sáu payment events. dbt tạo candidate, kiểm tra rồi mới cho publish. Failure drills cho thấy failed candidate không thay thế Gold pointer hiện tại.” |
| 3:00–3:40 | [Spark benchmark](../../cloud/week6/benchmark.md) | “Lab local đã xử lý 13,069,067 dòng taxi. Broadcast giảm shuffle bytes nhưng median chậm hơn 19.8%. Đây là kết quả đo của workload này, không phải kết luận tổng quát.” |
| 3:40–4:25 | [Mini3 API-to-Gold receipt](../../cloud/week7/closure/api_to_gold_e2e_receipt.json), [SCD2 receipt](../../cloud/week7/closure/dbt_scd2_history_receipt.json) | “Mini3 lấy một ngày đã ổn định cho ba địa điểm HCM, HN, DN và ghi ba dòng vào weather Gold. Snapshot minh họa ba version trạng thái tổng hợp. Đây không phải lịch sử khách hàng thực.” |
| 4:25–5:20 | [Airflow integration receipt](../../cloud/week7/closure/airflow_integration_receipt.md), [P7.5 closure](../../cloud/week7/closure/p75_airflow_correctness.md), [integration snapshot](../../EVIDENCE_INDEX.md) | “Airflow từng chạy một lần trong local Docker đối với GCP data plane. Bản sửa P7.5 được kiểm tra bằng no-egress scheduler harness; harness không chứng minh cloud retry hay scheduler được host. Ở snapshot mới nhất của Lane E, combined-head PR #9 có lỗi deadline scenario và đang chờ điều tra. Hãy kiểm tra checklist trước buổi trình bày để nói trạng thái hiện tại chính xác.” |
| 5:20–6:15 | [Cost table](cost_table.md), [cost and cleanup report](../../cloud/week7/closure/iam_cost_cleanup.md) | “Khoảng USD 0.095 là gross list-price estimate cho Cloud Run và BigQuery usage lịch sử trước free usage, không phải invoice. Project billed spend và VM inventory hiện tại chưa xác minh. Chúng ta không tạo VM hoặc managed Spark batch trong Lane D/E.” |
| 6:15–7:00 | [Syllabus coverage](../../SYLLABUS_COVERAGE.md), [engineering decisions](../../ENGINEERING_DECISIONS.md) | “Các phần còn thiếu được đánh dấu PARTIAL, NOT_RUN hoặc MENTOR_CONFIRMATION_PENDING. ENGINEERING_DECISIONS là AI-assisted first-person draft và cần tác giả tự review trước khi trình bày.” |

## Nếu được hỏi thêm

- Dùng [20 câu trả lời kỹ thuật](technical_defense.md), và chỉ khẳng định điều có receipt hoặc code pointer.
- Dùng [evidence index](../../EVIDENCE_INDEX.md) để phân biệt source/local, CI, historical live, và human evidence.
- Nếu giao diện hoặc artifact không khả dụng, chỉ trình bày file receipt tĩnh. Không tạo lại ảnh hay sửa receipt để làm đẹp.
- Không khẳng định course đã hoàn thành, mentor đã approve bằng văn bản, recurring schedule đang chạy, hoặc đã có final bill.