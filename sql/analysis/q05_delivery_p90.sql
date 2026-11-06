SELECT carrier, count(*) AS deliveries,
       round(avg(transit_days)::numeric,2) AS avg_days,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY transit_days) AS p90_days,
       round(100.0 * count(*) FILTER (WHERE late_over_3_days) / nullif(count(*),0),2)
         AS late_over_3_days_pct
FROM dw.fct_shipment WHERE status = 'delivered' AND transit_days IS NOT NULL
GROUP BY carrier ORDER BY p90_days DESC;
