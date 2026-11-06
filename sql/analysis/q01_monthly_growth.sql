-- Sales proxy excludes non-delivered orders; not GAAP revenue.
WITH monthly AS (
  SELECT month_start, fulfilled_sales_proxy AS sales
  FROM analytics.vw_monthly_sales
)
SELECT month_start, sales,
       lag(sales) OVER (ORDER BY month_start) AS previous_sales,
       round(100.0 * (sales - lag(sales) OVER (ORDER BY month_start)) /
             nullif(lag(sales) OVER (ORDER BY month_start), 0), 2) AS mom_growth_pct
FROM monthly ORDER BY month_start;
