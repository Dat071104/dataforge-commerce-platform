# Demo 5–7 phút cho mentor — Mini-project 1 + 2 hợp nhất

**Domain:** SaigonThreads (doanh nghiệp TMĐT thời trang **giả định**, tạo dữ liệu synthetic). **Không tuyên bố dữ liệu giao dịch thật hoặc revenue theo chuẩn kế toán.**

1. **0:00–0:45 Business problem** — Sales cần theo dõi giá trị hàng giao, Finance cần đối soát order/payment/return, Ops cần theo dõi giao hàng. Show `docs/metric_contract.md`, giải thích vì sao KPI chính xác quan trọng hơn biểu đồ đẹp.
2. **0:45–1:45 Mini-project 1 ingestion** — show CLI `generate`→`ingest`, 11 nguồn, `data/bronze`/active-run manifest SHA, validation quarantine. Explain subset source snapshots and atomic manifest promotion. Mention API weather optional + bounded retry and source labeling.
3. **1:45–3:00 Mini-project 2 modeling** — ERD dim_date/product/customer/geography and independent fct_order_item/payment/return/shipment. Show one SCD2 customer change and as-of join. Explain split payment (2 payments × 3 items would overcount if naively joined).
4. **3:00–4:00 SQL metrics** — compare CSV oracle `reference-metrics` to actual SQL totals; demonstrate 10 analytics scripts, EXPLAIN with real output (if PostgreSQL tests passed). Fail closed on mismatches.
5. **4:00–5:45 Power BI** — show Desktop's actual three pages *only if completed*, with Import model, single-direction relationships, date roles and regional RLS. If Desktop is unavailable, show the DAX/Power Query/relationship handoff and label it unrendered.
6. **5:45–6:30 Reliability** — show pytest and PostgreSQL integration tests, repeat-run invariance, changed-hash snapshot merges, transaction rollback and persistent dimension keys. Explain that facts still rebuild on each `db-build` and there is no CDC watermark.
7. **6:30–7:00 Roadmap** — GCS/BigQuery/Cloud Run Jobs only after local proof and explicit approval. Explain skills/CLI are reused from validated patterns rather than abstracted prematurely.

## Questions likely to be asked

- **Why not one big table?** Different fact grains cause join fanout; aggregate at own grain before reconciling.
- **Why SCD2?** Snapshot segments accurate at historical event time. Can't reconstruct changes absent history; synthetic fixtures demonstrate mechanism.
- **Does paid minus refunds equal revenue?** Not necessarily; posting dates and accounting recognition differ. Separate definitions and approvals.
- **Why no Spark now?** 3k/600k rows fit local/Postgres; Spark is useful when distributed computation justified, scheduled later.
- **Is weather causing late delivery?** Cannot infer causality from coarse city/day observational correlation.
- **How do you know it runs?** Show exact test commands and recorded outcomes, including any unverified GUI/cloud stages.
