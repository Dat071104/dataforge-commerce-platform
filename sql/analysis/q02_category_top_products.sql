WITH totals AS (
  SELECT p.category, p.product_id, sum(f.fulfilled_sales_proxy) AS sales
  FROM dw.fct_order_item f JOIN dw.dim_product p USING (product_key)
  GROUP BY p.category, p.product_id
), ranked AS (
  SELECT *, dense_rank() OVER (PARTITION BY category ORDER BY sales DESC) AS category_rank
  FROM totals
)
SELECT * FROM ranked WHERE category_rank <= 5 ORDER BY category, category_rank, product_id;
