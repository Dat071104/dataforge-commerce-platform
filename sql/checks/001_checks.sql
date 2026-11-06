-- Every assertion must return 0. Deliberately written as row counts for CLI.
WITH latest AS (
  SELECT DISTINCT ON (source) source, row_count
  FROM audit.load_runs
  ORDER BY source, loaded_at DESC, run_id DESC
), current_counts AS (
  SELECT 'geography' AS source, count(*) AS row_count FROM raw.geography
  UNION ALL SELECT 'customers', count(*) FROM raw.customers
  UNION ALL SELECT 'customer_segments', count(*) FROM raw.customer_segments
  UNION ALL SELECT 'products', count(*) FROM raw.products
  UNION ALL SELECT 'orders', count(*) FROM raw.orders
  UNION ALL SELECT 'order_items', count(*) FROM raw.order_items
  UNION ALL SELECT 'payments', count(*) FROM raw.payments
  UNION ALL SELECT 'shipments', count(*) FROM raw.shipments
  UNION ALL SELECT 'returns', count(*) FROM raw.returns
  UNION ALL SELECT 'inventory', count(*) FROM raw.inventory
  UNION ALL SELECT 'weather_daily', count(*) FROM raw.weather_daily
)
SELECT 'orphan_order_items' AS check_name, count(*) AS failures
  FROM raw.order_items i LEFT JOIN raw.orders o USING (order_id) WHERE o.order_id IS NULL
UNION ALL
SELECT 'orphan_products', count(*)
  FROM raw.order_items i LEFT JOIN raw.products p USING (product_id) WHERE p.product_id IS NULL
UNION ALL
SELECT 'orphan_payments', count(*)
  FROM raw.payments p LEFT JOIN raw.orders o USING (order_id) WHERE o.order_id IS NULL
UNION ALL
SELECT 'orphan_returns', count(*)
  FROM raw.returns r LEFT JOIN raw.order_items i USING (order_item_id) WHERE i.order_item_id IS NULL
UNION ALL
SELECT 'orphan_customers', count(*)
  FROM raw.orders o LEFT JOIN raw.customers c USING (customer_id) WHERE c.customer_id IS NULL
UNION ALL
SELECT 'orphan_geography', count(*)
  FROM raw.orders o LEFT JOIN raw.geography g USING (province_id) WHERE g.province_id IS NULL
UNION ALL
SELECT 'orphan_customer_segments', count(*)
  FROM raw.customer_segments s LEFT JOIN raw.customers c USING (customer_id)
  WHERE c.customer_id IS NULL
UNION ALL
SELECT 'orphan_inventory_products', count(*)
  FROM raw.inventory i LEFT JOIN raw.products p USING (product_id)
  WHERE p.product_id IS NULL
UNION ALL
SELECT 'missing_customer_version', count(*)
  FROM raw.orders o LEFT JOIN dw.dim_customer dc ON dc.customer_id = o.customer_id
    AND o.order_date >= dc.valid_from AND (dc.valid_to IS NULL OR o.order_date < dc.valid_to)
  WHERE dc.customer_key IS NULL
UNION ALL
SELECT 'customer_version_overlap', count(*)
  FROM dw.dim_customer a JOIN dw.dim_customer b
    ON a.customer_id = b.customer_id AND a.customer_key < b.customer_key
    AND a.valid_from < coalesce(b.valid_to, 'infinity'::date)
    AND b.valid_from < coalesce(a.valid_to, 'infinity'::date)
UNION ALL
SELECT 'fact_order_item_cardinality', abs((SELECT count(*) FROM raw.order_items) -
                                       (SELECT count(*) FROM dw.fct_order_item))
UNION ALL
SELECT 'fact_payment_cardinality', abs((SELECT count(*) FROM raw.payments) -
                                    (SELECT count(*) FROM dw.fct_payment))
UNION ALL
SELECT 'negative_net_order_value', count(*) FROM dw.fct_order_item WHERE net_order_value < 0
UNION ALL
SELECT 'refund_exceeds_line', count(*)
  FROM (SELECT r.order_item_id, sum(r.completed_refund) AS amount
        FROM dw.fct_return r GROUP BY 1) r
  JOIN dw.fct_order_item i USING (order_item_id)
  WHERE r.amount > i.net_order_value
UNION ALL
SELECT 'duplicate_current_customer', count(*)
  FROM (SELECT customer_id FROM dw.dim_customer WHERE is_current
        GROUP BY 1 HAVING count(*) <> 1) x
UNION ALL
SELECT 'missing_current_customer_version', count(*)
  FROM raw.customers c
  LEFT JOIN (SELECT customer_id, count(*) AS current_versions
             FROM dw.dim_customer WHERE is_current GROUP BY customer_id) d USING (customer_id)
  WHERE coalesce(d.current_versions, 0) <> 1
UNION ALL
SELECT 'current_customer_segment_mismatch', count(*)
  FROM raw.customers c JOIN dw.dim_customer d ON d.customer_id=c.customer_id AND d.is_current
  WHERE c.segment <> d.segment
UNION ALL
SELECT 'fact_shipment_cardinality', abs((SELECT count(*) FROM raw.shipments) -
                                    (SELECT count(*) FROM dw.fct_shipment))
UNION ALL
SELECT 'fact_return_cardinality', abs((SELECT count(*) FROM raw.returns) -
                                  (SELECT count(*) FROM dw.fct_return))
UNION ALL
SELECT 'fact_inventory_cardinality', abs((SELECT count(*) FROM raw.inventory) -
                                     (SELECT count(*) FROM dw.fct_inventory_snapshot))
UNION ALL
SELECT 'fact_weather_cardinality', abs((SELECT count(*) FROM raw.weather_daily) -
                                    (SELECT count(*) FROM dw.fct_weather_daily))
UNION ALL
SELECT 'orphan_shipments', count(*)
  FROM raw.shipments s LEFT JOIN raw.orders o USING (order_id) WHERE o.order_id IS NULL
UNION ALL
SELECT 'orphan_weather_geography', count(*)
  FROM raw.weather_daily w LEFT JOIN raw.geography g USING (province_id)
  WHERE g.province_id IS NULL
UNION ALL
SELECT 'missing_fact_order_dates', count(*)
  FROM dw.fct_order_item f LEFT JOIN dw.dim_date d ON d.date_key = f.order_date_key
  WHERE d.date_key IS NULL
UNION ALL
SELECT 'missing_fact_payment_dates', count(*)
  FROM dw.fct_payment f LEFT JOIN dw.dim_date d ON d.date_key = f.payment_date_key
  WHERE d.date_key IS NULL
UNION ALL
SELECT 'missing_fact_return_dates', count(*)
  FROM dw.fct_return r LEFT JOIN dw.dim_date d ON d.date_key = r.return_date_key
  WHERE d.date_key IS NULL
UNION ALL
SELECT 'missing_fact_ship_dates', count(*)
  FROM dw.fct_shipment s LEFT JOIN dw.dim_date d ON d.date_key = s.ship_date_key
  WHERE d.date_key IS NULL
UNION ALL
SELECT 'missing_fact_delivery_dates', count(*)
  FROM dw.fct_shipment s LEFT JOIN dw.dim_date d ON d.date_key = s.delivery_date_key
  WHERE s.delivery_date_key IS NOT NULL AND d.date_key IS NULL
UNION ALL
SELECT 'missing_fact_inventory_dates', count(*)
  FROM dw.fct_inventory_snapshot f LEFT JOIN dw.dim_date d ON d.date_key = f.snapshot_date_key
  WHERE d.date_key IS NULL
UNION ALL
SELECT 'missing_fact_weather_dates', count(*)
  FROM dw.fct_weather_daily f LEFT JOIN dw.dim_date d ON d.date_key = f.date_key
  WHERE d.date_key IS NULL
UNION ALL
SELECT 'missing_snapshot_audit_source', count(*)
  FROM current_counts c LEFT JOIN latest l USING (source)
  WHERE l.source IS NULL
UNION ALL
SELECT 'snapshot_audit_row_count_mismatch', count(*)
  FROM current_counts c JOIN latest l USING (source)
  WHERE l.row_count <> c.row_count
UNION ALL
SELECT 'negative_snapshot_audit_counts', count(*)
  FROM audit.load_runs
  WHERE row_count < 0 OR rows_inserted < 0 OR rows_updated < 0 OR rows_deleted < 0;
