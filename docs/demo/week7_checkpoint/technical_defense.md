# Technical defense · 20 questions

These are rehearsal answers, not a record of a mentor interview. The first-person decision log is an AI-assisted draft and requires author review. Keep each answer within the evidence linked from the [index](../../EVIDENCE_INDEX.md).

1. **Grain của từng fact và mart là gì?**
   <code>fct_order_item</code> có grain một dòng order-item; <code>fct_payment</code> là một payment event; <code>fct_return</code> là một return line; <code>fct_shipment</code> là một shipment. Week 7 <code>fct_week7_order_reconciliation</code> có một dòng hiện tại trên mỗi <code>order_id</code>, sau khi payments được aggregate riêng. Đây là synthetic commerce data.

2. **Pipeline idempotent ở đâu?**
   Local ingestion dùng content hash và atomic manifest; cloud objects dùng immutable generation/precondition; BigQuery dùng <code>MERGE</code>; Gold publication có candidate check và currentness pointer. Những cơ chế này làm repeated data effects có thể kiểm soát. Chúng không đảm bảo exactly-once API submission.

3. **Vì sao dùng <code>change_seq</code> thay vì chỉ <code>updated_at</code>? Nêu counterexample.**
   Hai events có thể có cùng timestamp. Nếu consumer dùng <code>updated_at &gt; cursor</code>, event đến muộn nhưng timestamp bằng cursor sẽ bị bỏ qua. <code>change_seq</code> được cấp tuần tự trong transaction nên cursor vẫn tiến; Lane D có test tái hiện counterexample.

4. **GCS generation dùng để làm gì?**
   Generation ghim chính xác version object mà manifest và downstream receipt đã đọc. Kết hợp SHA-256 để xác minh bytes và phát hiện generation mismatch. Generation không tự chứng minh rằng manifest đáng tin nếu cùng actor có thể sửa cả hai.

5. **Gold pointer hoạt động thế nào? Rollback ra sao?**
   Candidate được build, test và reconcile trước publication. Nếu gate fail thì candidate không được public. Commerce fence có thể làm view current rỗng khi upstream state đổi; các version bất biến vẫn giữ audit. Repo không chứng minh một nút rollback tự động; restore phải là thao tác publication có kiểm tra và có authorization riêng.

6. **Airflow, Workflows và Composer khác nhau thế nào? Vì sao chọn VM?**
   Cloud Workflows điều phối finite cloud steps; Airflow là scheduler/DAG framework; Cloud Composer là managed Airflow service. DataForge không chọn VM làm scheduler đã vận hành: Airflow từng chạy một lần trong local Docker; Composer và hosted Airflow không được triển khai. Local run giảm scope cho code evidence, nhưng không đáp ứng yêu cầu wholly-GCP nếu mentor đòi điều đó.

7. **Sensor dùng reschedule hay deferrable?**
   Bản cũ có reschedule sensor, nhưng Cloud Run task đã poll đồng bộ xong trước đó nên sensor không chứng minh asynchronous waiting có ý nghĩa. P7.5 bỏ sensor dư thừa. Bản hiện tại không claim một sensor async wait.

8. **SLA trong Airflow 3 ở đâu? Deadline Alerts dùng thế nào?**
   P7.5 dùng Airflow 3 Deadline Alert thay cho legacy SLA callback. No-egress harness kiểm tra deadline event và failure event riêng. Đây là local log/harness evidence; external email alert không được gửi bởi bản này.

9. **Lỗi nào retry, lỗi nào fail ngay?**
   Contract retry HTTP 408/429/5xx và transient poll reads trong giới hạn. HTTP 4xx như 403, ngày/identity/receipt/contract sai thì fail fast. Operation timeout mơ hồ cần operator xem Cloud Run trước khi replay.

10. **Retry có thể tạo duplicate không? Vì sao?**
    Provider request có thể lặp nếu timeout xảy ra sau khi Cloud Run nhận request nhưng trước khi caller nhận operation ID. Stable invocation ID, immutable writes, <code>MERGE</code>, và publication no-op bảo vệ published state; chúng không chứng minh exactly-once execution hay API call.

11. **Backfill một năm làm thế nào, nghẽn ở đâu?**
    Em chưa chạy year-long backfill. API contract hiện nhận một observation date mỗi request; một kế hoạch tương lai cần chia theo ngày, giới hạn concurrency, xác minh từng receipt, và đặt query/cost bound. Provider quota/rate, request volume và BigQuery scan là các điểm nghẽn cần đo trước khi xin phép chạy.

12. **Nếu mở rộng lên 1.000 địa điểm, phần nào hỏng trước?**
    Hệ thống hiện chỉ allowlist ba điểm, nên chưa có evidence ở quy mô đó. Best estimate là provider quota/request fan-out sẽ là giới hạn đầu tiên; payload volume, concurrency, rate limit, BigQuery partitioning và cost cần benchmark riêng. Đây là suy luận, không phải kết quả đo.

13. **Vì sao chờ bảy ngày? Provider sửa dữ liệu thì sao?**
    ERA5 cần settling delay trong contract. Raw response và typed Parquet được hash; response đã sửa tạo request identity mới và object version mới thay vì overwrite. Sau đó phải reconcile candidate trước publish. Không có guarantee provider sẽ không sửa lại sau thời gian này.

14. **IAM: service account nào được làm gì? Vì sao không dùng key?**
    Ingest identity ghi/đọc dưới Bronze prefix và merge landing; dbt identity đọc landing và ghi isolated candidates/Gold pointer; Workflows identity gọi đúng hai Cloud Run jobs và ghi ledger/log; Airflow identity có quyền invocation/read phù hợp; Scheduler caller tạm thời chỉ tạo Workflow execution. Dùng keyless identity để tránh long-lived service-account key.

15. **Secret nằm ở đâu, rotate thế nào?**
    Repo không có static service-account key. Runtime identity dùng keyless ADC; một số local harness mount file credential read-only làm fixture/runtime input, không phải secret được commit. No Secret Manager secret rotation event được claim ở đây; nếu workload cần real secret thì phải thiết kế scope và rotation policy riêng trước khi bật.

16. **Cost mỗi run là bao nhiêu? Budget có chặn spend không?**
    Em không thể đưa ra một đơn giá per-run đáng tin từ aggregate receipt. Weather receipt cho gross Cloud Run + BigQuery subtotal khoảng USD 0.095 qua nhiều executions, chưa gồm free usage và các dịch vụ chưa định giá. Project bill và current VM inventory unknown. Budget alert thông báo usage; không phải hard cap. [Cost table](cost_table.md).

17. **Vì sao broadcast join chậm hơn?**
    Quan sát được là broadcast giảm shuffle bytes nhưng median runtime chậm hơn 19.8%. Nguyên nhân cụ thể chưa được cô lập; scheduler overhead, serialization, memory pressure hoặc host contention chỉ là hypotheses. Em giữ số đo âm và không tuyên bố broadcast luôn chậm.

18. **SCD2 trên orders khác gì SCD2 trên dimension?**
    Receipt này lưu các order states mà synthetic dbt snapshot quan sát được; <code>ingested_at</code> tạo observation validity, không phải business-effective history. Dimension SCD2 thường version business attributes với surrogate key/effective dates để facts join đúng historical state. Repo không gọi order-state snapshot này là customer dimension.

19. **AI hỗ trợ phần nào, và kiểm chứng thế nào?**
    Engineering decision log và một phần tài liệu là AI-assisted draft; tác giả chưa ký duyệt reflection. Mỗi factual claim cần đối chiếu code, test, CI hoặc receipt. Em không gán cho AI hay bản thân bất kỳ mentor approval, course completion, screenshot, hay spend evidence nào khi không có artifact.

20. **Nếu làm lại từ đầu, em sẽ giản lược gì?**
    Em sẽ giữ một local commerce baseline, một bounded cloud batch, một local Spark lab và một Mini3 weather slice. Em sẽ thêm orchestrator hoặc hosted runtime chỉ khi checkpoint yêu cầu và có cost/permission gate; không giữ nhiều control plane nếu không mang lại evidence mới.