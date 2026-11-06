-- Line-item return rate; denominator is delivered line items, not orders.
WITH returns_per_line AS (
  SELECT order_item_id, bool_or(status = 'completed') AS was_returned
  FROM dw.fct_return GROUP BY order_item_id
)
SELECT p.category, count(*) AS fulfilled_lines,
       count(*) FILTER (WHERE coalesce(r.was_returned, false)) AS returned_lines,
       round(100.0 * count(*) FILTER (WHERE coalesce(r.was_returned, false)) /
             nullif(count(*),0), 2) AS return_line_rate_pct
FROM dw.fct_order_item f JOIN dw.dim_product p USING (product_key)
LEFT JOIN returns_per_line r USING (order_item_id)
WHERE f.order_status = 'delivered'
GROUP BY p.category ORDER BY return_line_rate_pct DESC;
