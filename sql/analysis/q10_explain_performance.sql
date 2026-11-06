-- Compare before/after indexing only with equivalent environment/data.
EXPLAIN (ANALYZE, BUFFERS)
SELECT f.product_key, sum(f.fulfilled_sales_proxy) AS sales
FROM dw.fct_order_item f
WHERE f.order_date_key BETWEEN 20220101 AND 20220131
GROUP BY f.product_key ORDER BY sales DESC LIMIT 10;
