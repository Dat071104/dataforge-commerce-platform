-- Monthly retained users by first DELIVERED order; excludes canceled/processing.
WITH visits AS (
  SELECT DISTINCT c.customer_id, date_trunc('month', d.calendar_date)::date AS order_month
  FROM dw.fct_order_item f
  JOIN dw.dim_customer c USING (customer_key)
  JOIN dw.dim_date d ON d.date_key = f.order_date_key
  WHERE f.order_status = 'delivered'
), cohorts AS (
  SELECT customer_id, min(order_month) AS cohort_month FROM visits GROUP BY 1
)
SELECT c.cohort_month,
       ((extract(year FROM v.order_month)-extract(year FROM c.cohort_month))*12 +
         extract(month FROM v.order_month)-extract(month FROM c.cohort_month))::int
           AS months_since_first,
       count(DISTINCT v.customer_id) AS active_customers
FROM visits v JOIN cohorts c USING (customer_id)
GROUP BY 1,2 ORDER BY 1,2;
