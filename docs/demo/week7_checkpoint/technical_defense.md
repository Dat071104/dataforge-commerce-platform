# Technical defense · 15 questions

These are draft answers in Vietnamese. Personalize them before presenting and keep only claims you can personally explain from the code or receipts.

1. **DataForge giải quyết bài toán gì?**<br>
   Đây là portfolio học Data Engineering trên dữ liệu commerce tổng hợp. Em giữ riêng local commerce, các bài tập GCP, lab Spark taxi và weather Mini3 vì grain và lifecycle khác nhau. Em không trình bày nó như một service production hay hệ thống kế toán.

2. **Vì sao không join trực tiếp mọi fact với nhau?**<br>
   Một order item, payment, return và shipment là các grain khác nhau. Join ở grain thô có thể nhân bản tiền hoặc số lượng. Em aggregate/đối soát theo key có hợp đồng rõ ràng và dùng metric contract để nói đúng định nghĩa.

3. **Workflows và Airflow chịu trách nhiệm gì? Vì sao gọi Google API bằng REST?**<br>
   Workflows điều phối finite Cloud Run Jobs cho đường GCP. Airflow 3.4 là một integration DAG chạy local Docker, không phải scheduler hosted. DAG dùng AuthorizedSession với identity keyless, resource path cố định và allowlist để giới hạn phạm vi. Cách này dễ kiểm soát nhưng em phải tự quản lý polling và phân loại lỗi; provider operator chỉ nên thay thế sau khi xác minh tương thích Airflow 3.4 và auth.

4. **Lỗi scheduled DagRun với empty conf là gì, và P7.5 sửa ra sao?**<br>
   DAG cũ yêu cầu <code>dag_run.conf.mode=cloud_integration</code>, trong khi scheduler bình thường không gửi conf đó, nên run dừng trước ingest. P7.5 dùng Param mặc định đã validate cho mode scheduled và ngày theo interval, còn quyền chạm cloud là cờ deployment riêng, mặc định OFF. Manual date vẫn phải qua validation. 32 contract tests chạy với package Airflow 3.4.0 trong virtualenv cô lập; pinned Linux Docker test chưa chạy được vì Docker engine unavailable và Airflow không hỗ trợ native Windows.

5. **Sensor trong receipt cũ có thực sự chờ bất đồng bộ không?**<br>
   Không. Task gọi Cloud Run đã poll operation đến terminal state rồi sensor mới chạy. Vì vậy sensor thường chỉ xác nhận receipt sau khi job xong; nó không chứng minh async waiting. P7.5 bỏ sensor dư thừa và dùng bounded receipt read. Em không claim đã demo async Airflow sensor.

6. **Vì sao dùng sequence thay vì chỉ dựa vào <code>updated_at</code>?**<br>
   Nhiều event có thể cùng timestamp, còn sequence tạo thứ tự replay ổn định và checkpoint rõ ràng. Nó giúp xử lý tombstone, gap, backfill và retry có thể kiểm tra. Sequence là source ordering cho bài tập này, không phải CDC streaming.

7. **Tại sao đợi 7 ngày cho ERA5?**<br>
   Đây là settling policy bảo thủ cho dữ liệu lịch sử, không phải khẳng định provider đã chốt vĩnh viễn mọi giá trị. Nếu provider sửa dữ liệu, response hash tạo request identity mới và pipeline giữ provenance của lần đó.

8. **Nếu provider sửa dữ liệu cũ thì theo dõi thế nào?**<br>
   Request ID dựa trên date, danh sách province và digest response; manifest ghi source hash, object generation, và provenance. Bản sửa tạo identity mới, còn Bronze cũ vẫn immutable. dbt chọn request đã verify mới nhất cho grain date/province/source/model.

9. **Gold pointer hỗ trợ recovery/rollback ra sao?**<br>
   Candidate được build và test trước publication. Week 7 commerce dùng versioned output và currentness fence; nếu failure xảy ra sau Silver commit nhưng trước publish, view không lộ candidate mới và exact-manifest replay có thể hoàn tất publish. Mini3 weather có pointer riêng. Em không nói rollback tự động cho mọi lỗi; các version và receipt giữ bằng chứng để reviewer kiểm tra.

10. **1,000 địa điểm × 365 ngày có chạy được với code hiện tại không?**<br>
    Không nên suy ra từ demo ba địa điểm. Grain lý thuyết là 365,000 location/date rows, nhưng API quota, số request, concurrency, retry, object count, partitioning, late correction và cost phải benchmark trước. Em sẽ mở rộng theo batch, đặt giới hạn và đo số request/bytes trước khi hứa throughput.

11. **SCD2 proof có phải customer dimension không?**<br>
    Không. Đó là bảng order-state synthetic để chứng minh dbt snapshot tạo ba version, validity window nối tiếp, một current row và không tạo version mới khi replay unchanged. Nó không phải thiết kế SCD2 customer/location dimension hay bằng chứng lịch sử nghiệp vụ thật.

12. **Bytes billed của BigQuery có phải invoice không? Budget alert có chặn spend không?**<br>
    Không. Billed bytes và list-rate là usage estimate; billing export/credits/free tier và settled invoice có thể khác. Repo ghi actual settlement là unknown. Budget alert chỉ thông báo theo ngưỡng, không phải hard cap; hiện không có budget alert được claim là đã cấu hình.

13. **Tại sao broadcast join lại chậm hơn?**<br>
    Trên máy local này broadcast giảm shuffle nhưng tăng memory/serialization và scheduling overhead. Median baseline là 213.924 giây, broadcast là 256.307 giây, chậm hơn 19.8%. Đây là một workload/máy cụ thể, không phải quy luật cho mọi cluster.

14. **Retry và no-op bảo vệ điều gì? Có exactly-once không?**<br>
    Stable invocation ID, immutable upload precondition, landing MERGE và publication hash/check giúp retry hoặc exact replay không nhân bản published state. Nhưng timeout sau <code>jobs.run</code> có thể khiến operation đầu vẫn chạy trong lúc Airflow retry gửi lại; provider API call có thể lặp. Vì vậy em nói at-least-once invocation với idempotent effects, không claim exactly-once.

15. **Credential và AI-assisted engineering được kiểm soát thế nào?**<br>
    Runtime dùng keyless ADC/impersonation và scoped service account; không có static service-account key trong evidence. AI có thể hỗ trợ soạn code hoặc tài liệu, nhưng em chỉ nên nhận phần em đã tự đọc và kiểm chứng. Em sẽ trỏ từng claim về test hoặc receipt, không nhận human review, certificate hay mentor approval khi chưa có artifact tương ứng.
