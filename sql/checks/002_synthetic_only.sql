SELECT 'payment_order_variance_synthetic_fixture' AS check_name, count(*) AS failures
FROM analytics.vw_order_reconciliation WHERE collection_variance <> 0;
