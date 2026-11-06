-- Run on seed=42, 3000-order synthetic fixture and compare with
-- docs/expected_fixture_metrics.json generated without SQL.
SELECT 'fulfilled_sales_proxy_vnd' AS metric,
       sum(fulfilled_sales_proxy)::numeric(24,2) AS value FROM dw.fct_order_item
UNION ALL
SELECT 'fulfilled_cogs_proxy_vnd', sum(fulfilled_cogs_proxy)::numeric(24,2)
FROM dw.fct_order_item
UNION ALL
SELECT 'collected_vnd', sum(collected_amount)::numeric(24,2) FROM dw.fct_payment
UNION ALL
SELECT 'completed_refunds_vnd', sum(completed_refund)::numeric(24,2) FROM dw.fct_return
UNION ALL
SELECT 'collection_variance_vnd', sum(collection_variance)::numeric(24,2)
FROM analytics.vw_order_reconciliation;
