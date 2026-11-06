SELECT order_id, ordered_net_value, expected_collection_proxy,
       collected, completed_refunds, collection_variance
FROM analytics.vw_order_reconciliation
ORDER BY abs(collection_variance) DESC, order_id LIMIT 100;
