WITH recent_snapshot AS (
  SELECT max(snapshot_date_key) AS snapshot_day FROM dw.fct_inventory_snapshot
), sold AS (
  SELECT product_key, sum(quantity) FILTER (WHERE order_status='delivered') AS sold_units
  FROM dw.fct_order_item GROUP BY 1
)
SELECT p.product_id, p.category, i.quantity_in_stock, i.reorder_point,
       coalesce(s.sold_units, 0) AS fulfilled_units_in_sample,
       (i.quantity_in_stock < i.reorder_point) AS reorder_flag
FROM dw.fct_inventory_snapshot i JOIN recent_snapshot r ON i.snapshot_date_key=r.snapshot_day
JOIN dw.dim_product p USING(product_key)
LEFT JOIN sold s USING(product_key)
ORDER BY reorder_flag DESC, fulfilled_units_in_sample ASC LIMIT 50;
-- Observational units cover the sample period, not a monthly sell-through rate.
