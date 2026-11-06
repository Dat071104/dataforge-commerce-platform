-- Consolidate SCD2 versions by stable business ID before LTV calculations.
WITH totals AS (
  SELECT c.customer_id, sum(f.fulfilled_sales_proxy) AS sales,
         count(DISTINCT f.order_id) FILTER (WHERE f.order_status = 'delivered') AS orders
  FROM dw.fct_order_item f JOIN dw.dim_customer c USING (customer_key)
  GROUP BY c.customer_id
)
SELECT customer_id, orders, sales,
       dense_rank() OVER (ORDER BY sales DESC) AS value_rank,
       sum(sales) OVER (ORDER BY sales DESC, customer_id) AS running_portfolio_sales
FROM totals ORDER BY value_rank, customer_id LIMIT 30;
