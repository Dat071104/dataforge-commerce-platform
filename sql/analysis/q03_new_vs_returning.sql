-- First delivered business order by stable customer_id, not SCD2 surrogate.
WITH visits AS (
  SELECT DISTINCT c.customer_id, f.order_id, d.calendar_date AS order_date
  FROM dw.fct_order_item f
  JOIN dw.dim_customer c USING (customer_key)
  JOIN dw.dim_date d ON d.date_key = f.order_date_key
  WHERE f.order_status = 'delivered'
), first_order AS (
  SELECT customer_id, min(order_date) AS first_date FROM visits GROUP BY 1
), classified AS (
  SELECT date_trunc('month', d.calendar_date)::date AS month_start,
         CASE WHEN d.calendar_date = fo.first_date THEN 'first_purchase_date'
              ELSE 'returning_date' END AS purchase_type,
         f.fulfilled_sales_proxy AS sales
  FROM dw.fct_order_item f
  JOIN dw.dim_customer c USING (customer_key)
  JOIN first_order fo USING (customer_id)
  JOIN dw.dim_date d ON d.date_key = f.order_date_key
  WHERE f.order_status = 'delivered'
)
SELECT month_start, purchase_type, sum(sales) AS sales
FROM classified GROUP BY 1,2 ORDER BY 1,2;
-- A customer's multiple orders on first date are classified consistently.
