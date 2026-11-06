-- Optional candidate index for q10_explain_performance.sql.
-- Capture equivalent EXPLAIN (ANALYZE, BUFFERS) plans before running this file.
-- It may not help when the date predicate reads a large share of the fact table.
CREATE INDEX IF NOT EXISTS fct_item_q10_covering_idx
  ON dw.fct_order_item(order_date_key, product_key)
  INCLUDE (fulfilled_sales_proxy);
ANALYZE dw.fct_order_item;
