# Analytics SQL catalog

All scripts run against the Gold layer using PostgreSQL 16. The synthetic fixture is the main correctness oracle; source-specific semantics must be reviewed before applying these questions to external data.

| Query | Business meaning | Technique / grain guard |
|---|---|---|
| `q01_monthly_growth.sql` | Delivered sales proxy by month and month-over-month change. This proxy is not accounting revenue. | Monthly aggregation and `LAG`; order date. |
| `q02_category_top_products.sql` | Top products within product categories by delivered sales proxy. | Aggregate item facts before joining product attributes. |
| `q03_new_vs_returning.sql` | Delivered order value split by a customer's first delivered business order. | Window function over stable natural `customer_id`, not SCD2 surrogate; multiple orders on first day classify consistently. |
| `q04_return_rates.sql` | Completed return rate over delivered item lines. | Return denominator is delivered item lines, not order count; avoid multiplying line values. |
| `q05_delivery_p90.sql` | Delivered shipment transit-time distribution and inclusive P90 by carrier. | Delivered shipments with non-null transit duration; shipment grain and delivery-date context are explicit. |
| `q06_customer_lifetime.sql` | Delivered sales proxy by stable customer across SCD2 versions. | Consolidate versions by `customer_id` before lifetime grouping. |
| `q07_cohort_retention.sql` | Monthly retained customers by first delivered-order cohort. | Window/cohort aggregation; canceled and processing orders excluded. |
| `q08_order_payment_reconciliation.sql` | Successful payment collection compared with delivered sales proxy, by order. | Independently aggregate item and payment facts to order before join; refunds remain a separate event-date metric. |
| `q09_inventory_stock_risk.sql` | Product snapshots below reorder point. | Snapshot grain; observations describe the sample period and are not monthly sell-through. |
| `q10_explain_performance.sql` | Inspect the planner's execution path for the selected analytics workload. | `EXPLAIN (ANALYZE, BUFFERS)`; compare only against a recorded run on the same data, hardware, cache and query. |

Run every query from the repository root:

```powershell
Get-ChildItem .\sql\analysis\q*.sql | ForEach-Object {
  .\.venv\Scripts\dataforge.exe query $_.BaseName
}
```

The scripts are reproducible analysis examples, not production service-level claims. Benchmark observations and limitations are kept in [`performance_benchmark.md`](performance_benchmark.md).
