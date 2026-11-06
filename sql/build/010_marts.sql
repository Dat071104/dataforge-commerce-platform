-- Transactional mart rebuild with persistent dimension keys.
-- The Python runner executes this full file in one PostgreSQL transaction.
CREATE SCHEMA IF NOT EXISTS dw;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS dw.dim_date (
  date_key INTEGER PRIMARY KEY,
  calendar_date DATE NOT NULL,
  year INTEGER NOT NULL,
  month INTEGER NOT NULL,
  month_start DATE NOT NULL,
  quarter INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS dim_date_calendar_idx
  ON dw.dim_date(calendar_date);

CREATE TABLE IF NOT EXISTS dw.dim_product (
  product_key INTEGER PRIMARY KEY,
  product_id TEXT NOT NULL,
  category TEXT NOT NULL,
  subcategory TEXT NOT NULL,
  base_price NUMERIC(18,2) NOT NULL,
  unit_cogs NUMERIC(18,2) NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS dim_product_business_idx
  ON dw.dim_product(product_id);

CREATE TABLE IF NOT EXISTS dw.dim_geography (
  geography_key INTEGER PRIMARY KEY,
  province_id TEXT NOT NULL,
  province TEXT NOT NULL,
  region TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS dim_geo_business_idx
  ON dw.dim_geography(province_id);

CREATE TABLE IF NOT EXISTS dw.dim_customer (
  customer_key INTEGER PRIMARY KEY,
  customer_id TEXT NOT NULL,
  segment TEXT NOT NULL,
  valid_from DATE NOT NULL,
  valid_to DATE,
  is_current BOOLEAN NOT NULL,
  signup_date DATE NOT NULL,
  geography_key INTEGER NOT NULL,
  customer_region TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS dim_customer_history_idx
  ON dw.dim_customer(customer_id, valid_from);

CREATE TABLE IF NOT EXISTS audit.dimension_key_state (
  dimension_name TEXT PRIMARY KEY,
  last_key BIGINT NOT NULL CHECK (last_key >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed monotonic key state from pre-P4 dimensions. Never lower an existing
-- high-water mark when a source snapshot removes its largest natural key.
INSERT INTO audit.dimension_key_state (dimension_name, last_key)
SELECT 'product', coalesce(max(product_key), 0) FROM dw.dim_product
ON CONFLICT (dimension_name) DO UPDATE SET
  last_key = greatest(audit.dimension_key_state.last_key, EXCLUDED.last_key),
  updated_at = now();
INSERT INTO audit.dimension_key_state (dimension_name, last_key)
SELECT 'geography', coalesce(max(geography_key), 0) FROM dw.dim_geography
ON CONFLICT (dimension_name) DO UPDATE SET
  last_key = greatest(audit.dimension_key_state.last_key, EXCLUDED.last_key),
  updated_at = now();
INSERT INTO audit.dimension_key_state (dimension_name, last_key)
SELECT 'customer', coalesce(max(customer_key), 0) FROM dw.dim_customer
ON CONFLICT (dimension_name) DO UPDATE SET
  last_key = greatest(audit.dimension_key_state.last_key, EXCLUDED.last_key),
  updated_at = now();

-- Serialize concurrent builds' key allocation until this transaction commits.
SELECT dimension_name, last_key
FROM audit.dimension_key_state
WHERE dimension_name IN ('product', 'geography', 'customer')
ORDER BY dimension_name
FOR UPDATE;

-- The date key is a natural YYYYMMDD key. Keep prior dates and add any newly
-- observed fact dates, including payment, return, ship, delivery, inventory,
-- and weather events.
WITH event_dates AS (
  SELECT order_date AS event_date FROM raw.orders
  UNION ALL SELECT payment_date FROM raw.payments
  UNION ALL SELECT return_date FROM raw.returns
  UNION ALL SELECT ship_date FROM raw.shipments
  UNION ALL SELECT delivery_date FROM raw.shipments WHERE delivery_date IS NOT NULL
  UNION ALL SELECT snapshot_date FROM raw.inventory
  UNION ALL SELECT observation_date FROM raw.weather_daily
), date_bounds AS (
  SELECT min(event_date)::timestamp AS first_date,
         (max(event_date) + 40)::timestamp AS last_date
  FROM event_dates
), calendar AS (
  SELECT (to_char(d, 'YYYYMMDD'))::integer AS date_key,
         d::date AS calendar_date,
         extract(year FROM d)::integer AS year,
         extract(month FROM d)::integer AS month,
         date_trunc('month', d)::date AS month_start,
         extract(quarter FROM d)::integer AS quarter
  FROM date_bounds b
  CROSS JOIN LATERAL generate_series(b.first_date, b.last_date, interval '1 day') AS dates(d)
)
INSERT INTO dw.dim_date (date_key, calendar_date, year, month, month_start, quarter)
SELECT date_key, calendar_date, year, month, month_start, quarter
FROM calendar
ON CONFLICT (date_key) DO UPDATE SET
  calendar_date = EXCLUDED.calendar_date,
  year = EXCLUDED.year,
  month = EXCLUDED.month,
  month_start = EXCLUDED.month_start,
  quarter = EXCLUDED.quarter;

-- Preserve existing product keys, including keys from the pre-P4 dimension
-- tables. New products receive keys above the current maximum.
UPDATE dw.dim_product AS d
SET category = p.category,
    subcategory = p.subcategory,
    base_price = p.base_price,
    unit_cogs = p.unit_cogs
FROM raw.products p
WHERE d.product_id = p.product_id
  AND (d.category, d.subcategory, d.base_price, d.unit_cogs)
      IS DISTINCT FROM (p.category, p.subcategory, p.base_price, p.unit_cogs);

WITH base AS (
  SELECT last_key AS max_key
  FROM audit.dimension_key_state WHERE dimension_name = 'product'
), new_products AS (
  SELECT p.*, row_number() OVER (ORDER BY p.product_id)::integer AS key_offset
  FROM raw.products p
  WHERE NOT EXISTS (
    SELECT 1 FROM dw.dim_product d WHERE d.product_id = p.product_id
  )
)
INSERT INTO dw.dim_product
  (product_key, product_id, category, subcategory, base_price, unit_cogs)
SELECT (base.max_key + new_products.key_offset)::integer,
       product_id, category, subcategory, base_price, unit_cogs
FROM new_products CROSS JOIN base;

UPDATE audit.dimension_key_state AS state
SET last_key = greatest(state.last_key, coalesce((SELECT max(product_key) FROM dw.dim_product), 0)),
    updated_at = now()
WHERE state.dimension_name = 'product';

DELETE FROM dw.dim_product d
WHERE NOT EXISTS (SELECT 1 FROM raw.products p WHERE p.product_id = d.product_id);

-- Province natural keys follow the same preserve-and-append rule.
UPDATE dw.dim_geography AS d
SET province = g.province, region = g.region
FROM raw.geography g
WHERE d.province_id = g.province_id
  AND (d.province, d.region) IS DISTINCT FROM (g.province, g.region);

WITH base AS (
  SELECT last_key AS max_key
  FROM audit.dimension_key_state WHERE dimension_name = 'geography'
), new_geography AS (
  SELECT g.*, row_number() OVER (ORDER BY g.province_id)::integer AS key_offset
  FROM raw.geography g
  WHERE NOT EXISTS (
    SELECT 1 FROM dw.dim_geography d WHERE d.province_id = g.province_id
  )
)
INSERT INTO dw.dim_geography (geography_key, province_id, province, region)
SELECT (base.max_key + new_geography.key_offset)::integer,
       province_id, province, region
FROM new_geography CROSS JOIN base;

UPDATE audit.dimension_key_state AS state
SET last_key = greatest(state.last_key, coalesce((SELECT max(geography_key) FROM dw.dim_geography), 0)),
    updated_at = now()
WHERE state.dimension_name = 'geography';

DELETE FROM dw.dim_geography d
WHERE NOT EXISTS (SELECT 1 FROM raw.geography g WHERE g.province_id = d.province_id);

-- Customer Type 2 versions use (customer_id, valid_from) as their natural key.
-- Updating an existing version keeps its surrogate key; new versions append.
UPDATE dw.dim_customer AS d
SET segment = s.segment,
    valid_to = s.valid_to,
    is_current = (s.valid_to IS NULL),
    signup_date = c.signup_date,
    geography_key = g.geography_key,
    customer_region = g.region
FROM raw.customer_segments s
JOIN raw.customers c ON c.customer_id = s.customer_id
JOIN dw.dim_geography g ON g.province_id = c.province_id
WHERE d.customer_id = s.customer_id
  AND d.valid_from = s.valid_from
  AND (d.segment, d.valid_to, d.is_current, d.signup_date,
       d.geography_key, d.customer_region)
      IS DISTINCT FROM (s.segment, s.valid_to, (s.valid_to IS NULL), c.signup_date,
                        g.geography_key, g.region);

WITH base AS (
  SELECT last_key AS max_key
  FROM audit.dimension_key_state WHERE dimension_name = 'customer'
), new_versions AS (
  SELECT s.customer_id, s.segment, s.valid_from, s.valid_to,
         (s.valid_to IS NULL) AS is_current, c.signup_date,
         g.geography_key, g.region AS customer_region,
         row_number() OVER (ORDER BY s.customer_id, s.valid_from)::integer AS key_offset
  FROM raw.customer_segments s
  JOIN raw.customers c ON c.customer_id = s.customer_id
  JOIN dw.dim_geography g ON g.province_id = c.province_id
  WHERE NOT EXISTS (
    SELECT 1 FROM dw.dim_customer d
    WHERE d.customer_id = s.customer_id AND d.valid_from = s.valid_from
  )
)
INSERT INTO dw.dim_customer
  (customer_key, customer_id, segment, valid_from, valid_to, is_current,
   signup_date, geography_key, customer_region)
SELECT (base.max_key + new_versions.key_offset)::integer,
       customer_id, segment, valid_from, valid_to, is_current,
       signup_date, geography_key, customer_region
FROM new_versions CROSS JOIN base;

UPDATE audit.dimension_key_state AS state
SET last_key = greatest(state.last_key, coalesce((SELECT max(customer_key) FROM dw.dim_customer), 0)),
    updated_at = now()
WHERE state.dimension_name = 'customer';

DELETE FROM dw.dim_customer d
WHERE NOT EXISTS (
  SELECT 1
  FROM raw.customer_segments s
  JOIN raw.customers c ON c.customer_id = s.customer_id
  WHERE s.customer_id = d.customer_id AND s.valid_from = d.valid_from
);

CREATE TABLE IF NOT EXISTS dw.fct_order_item (
  order_item_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  order_date_key INTEGER NOT NULL,
  customer_key INTEGER NOT NULL,
  product_key INTEGER NOT NULL,
  geography_key INTEGER NOT NULL,
  order_status TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  unit_price NUMERIC(18,2) NOT NULL,
  discount_pct NUMERIC(8,4) NOT NULL,
  gross_item_value NUMERIC(18,2) NOT NULL,
  discount_value NUMERIC(18,2) NOT NULL,
  net_order_value NUMERIC(18,2) NOT NULL,
  fulfilled_sales_proxy NUMERIC(18,2) NOT NULL,
  fulfilled_cogs_proxy NUMERIC(18,2) NOT NULL
);
CREATE TABLE IF NOT EXISTS dw.fct_payment (
  payment_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  geography_key INTEGER NOT NULL,
  payment_date_key INTEGER NOT NULL,
  method TEXT NOT NULL,
  status TEXT NOT NULL,
  amount NUMERIC(18,2) NOT NULL,
  collected_amount NUMERIC(18,2) NOT NULL
);
CREATE TABLE IF NOT EXISTS dw.fct_return (
  return_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  order_item_id TEXT NOT NULL,
  geography_key INTEGER NOT NULL,
  return_date_key INTEGER NOT NULL,
  status TEXT NOT NULL,
  refund_amount NUMERIC(18,2) NOT NULL,
  completed_refund NUMERIC(18,2) NOT NULL
);
CREATE TABLE IF NOT EXISTS dw.fct_shipment (
  shipment_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  geography_key INTEGER NOT NULL,
  ship_date_key INTEGER NOT NULL,
  delivery_date_key INTEGER,
  carrier TEXT NOT NULL,
  status TEXT NOT NULL,
  transit_days INTEGER,
  late_over_3_days BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS dw.fct_inventory_snapshot (
  snapshot_date_key INTEGER NOT NULL,
  product_key INTEGER NOT NULL,
  quantity_in_stock INTEGER NOT NULL,
  reorder_point INTEGER NOT NULL,
  PRIMARY KEY (snapshot_date_key, product_key)
);
CREATE TABLE IF NOT EXISTS dw.fct_weather_daily (
  date_key INTEGER NOT NULL,
  geography_key INTEGER NOT NULL,
  precipitation_mm NUMERIC(12,3),
  temp_max_c NUMERIC(8,2),
  source TEXT NOT NULL,
  PRIMARY KEY (date_key, geography_key)
);

-- Facts are rebuilt from their authoritative raw grains after dimensions are
-- reconciled. The enclosing transaction keeps this promotion atomic.
TRUNCATE TABLE dw.fct_order_item, dw.fct_payment, dw.fct_return,
  dw.fct_shipment, dw.fct_inventory_snapshot, dw.fct_weather_daily;

INSERT INTO dw.fct_order_item
SELECT i.order_item_id, o.order_id,
       (to_char(o.order_date, 'YYYYMMDD'))::integer AS order_date_key,
       dc.customer_key, p.product_key, g.geography_key,
       o.status AS order_status,
       i.quantity, i.unit_price, i.discount_pct,
       (i.quantity * i.unit_price)::numeric(18,2) AS gross_item_value,
       (i.quantity * i.unit_price * i.discount_pct)::numeric(18,2) AS discount_value,
       (i.quantity * i.unit_price * (1 - i.discount_pct))::numeric(18,2) AS net_order_value,
       CASE WHEN o.status = 'delivered'
            THEN (i.quantity * i.unit_price * (1 - i.discount_pct))::numeric(18,2)
            ELSE 0::numeric(18,2) END AS fulfilled_sales_proxy,
       CASE WHEN o.status = 'delivered'
            THEN (i.quantity * p.unit_cogs)::numeric(18,2)
            ELSE 0::numeric(18,2) END AS fulfilled_cogs_proxy
FROM raw.order_items i
JOIN raw.orders o ON o.order_id = i.order_id
JOIN dw.dim_product p ON p.product_id = i.product_id
JOIN dw.dim_geography g ON g.province_id = o.province_id
JOIN dw.dim_customer dc ON dc.customer_id = o.customer_id
  AND o.order_date >= dc.valid_from
  AND (dc.valid_to IS NULL OR o.order_date < dc.valid_to);

INSERT INTO dw.fct_payment
SELECT p.payment_id, p.order_id, g.geography_key,
       (to_char(p.payment_date,'YYYYMMDD'))::integer AS payment_date_key,
       p.method, p.status, p.amount,
       CASE WHEN p.status = 'success' THEN p.amount ELSE 0::numeric END AS collected_amount
FROM raw.payments p
JOIN raw.orders o ON o.order_id = p.order_id
JOIN dw.dim_geography g ON g.province_id = o.province_id;

INSERT INTO dw.fct_return
SELECT r.return_id, i.order_id, r.order_item_id, g.geography_key,
       (to_char(r.return_date,'YYYYMMDD'))::integer AS return_date_key,
       r.status, r.refund_amount,
       CASE WHEN r.status = 'completed' THEN r.refund_amount ELSE 0::numeric END AS completed_refund
FROM raw.returns r
JOIN raw.order_items i ON i.order_item_id = r.order_item_id
JOIN raw.orders o ON o.order_id = i.order_id
JOIN dw.dim_geography g ON g.province_id = o.province_id;

INSERT INTO dw.fct_shipment
SELECT s.shipment_id, s.order_id, g.geography_key,
       (to_char(s.ship_date,'YYYYMMDD'))::integer AS ship_date_key,
       (to_char(s.delivery_date,'YYYYMMDD'))::integer AS delivery_date_key,
       s.carrier, s.status,
       (s.delivery_date - s.ship_date) AS transit_days,
       CASE WHEN s.delivery_date IS NOT NULL AND (s.delivery_date - s.ship_date) > 3
            THEN true ELSE false END AS late_over_3_days
FROM raw.shipments s
JOIN raw.orders o ON o.order_id = s.order_id
JOIN dw.dim_geography g ON g.province_id = o.province_id;

INSERT INTO dw.fct_inventory_snapshot
SELECT (to_char(i.snapshot_date,'YYYYMMDD'))::integer AS snapshot_date_key,
       p.product_key, i.quantity_in_stock, i.reorder_point
FROM raw.inventory i
JOIN dw.dim_product p ON p.product_id = i.product_id;

INSERT INTO dw.fct_weather_daily
SELECT (to_char(w.observation_date,'YYYYMMDD'))::integer AS date_key,
       g.geography_key, w.precipitation_mm, w.temp_max_c, w.source
FROM raw.weather_daily w
JOIN dw.dim_geography g ON g.province_id = w.province_id;

CREATE INDEX IF NOT EXISTS fct_item_order_date_idx ON dw.fct_order_item(order_date_key);
CREATE INDEX IF NOT EXISTS fct_item_product_idx ON dw.fct_order_item(product_key);
CREATE INDEX IF NOT EXISTS fct_item_order_idx ON dw.fct_order_item(order_id);
CREATE INDEX IF NOT EXISTS fct_payment_order_idx ON dw.fct_payment(order_id);
CREATE INDEX IF NOT EXISTS fct_return_order_idx ON dw.fct_return(order_id);
CREATE INDEX IF NOT EXISTS fct_shipment_ship_day_idx ON dw.fct_shipment(ship_date_key);

-- Aggregate each independent fact before reconciling by order; never multiply
-- split payments by joining them to order-item rows.
CREATE OR REPLACE VIEW analytics.vw_order_reconciliation AS
WITH items AS (
  SELECT order_id, sum(net_order_value) AS ordered_net_value,
         sum(fulfilled_sales_proxy) AS expected_collection_proxy
  FROM dw.fct_order_item GROUP BY order_id
), paid AS (
  SELECT order_id, sum(collected_amount) AS collected
  FROM dw.fct_payment GROUP BY order_id
), refunded AS (
  SELECT order_id, sum(completed_refund) AS completed_refunds
  FROM dw.fct_return GROUP BY order_id
)
SELECT i.order_id, (to_char(o.order_date,'YYYYMMDD'))::integer AS order_date_key,
       g.geography_key, i.ordered_net_value, i.expected_collection_proxy,
       coalesce(p.collected, 0)::numeric(18,2) AS collected,
       coalesce(r.completed_refunds, 0)::numeric(18,2) AS completed_refunds,
       (coalesce(p.collected, 0) - i.expected_collection_proxy)::numeric(18,2) AS collection_variance
FROM items i
JOIN raw.orders o ON o.order_id = i.order_id
JOIN dw.dim_geography g ON g.province_id = o.province_id
LEFT JOIN paid p ON i.order_id = p.order_id
LEFT JOIN refunded r ON i.order_id = r.order_id;

CREATE OR REPLACE VIEW analytics.vw_daily_sales AS
SELECT d.calendar_date AS order_date,
       count(DISTINCT f.order_id) FILTER (WHERE f.order_status = 'delivered') AS delivered_orders,
       sum(f.fulfilled_sales_proxy) AS fulfilled_sales_proxy,
       sum(f.fulfilled_cogs_proxy) AS fulfilled_cogs_proxy
FROM dw.fct_order_item f
JOIN dw.dim_date d ON d.date_key = f.order_date_key
GROUP BY d.calendar_date;

CREATE OR REPLACE VIEW analytics.vw_monthly_sales AS
SELECT date_trunc('month', order_date)::date AS month_start,
       sum(delivered_orders) AS delivered_orders,
       sum(fulfilled_sales_proxy)::numeric(18,2) AS fulfilled_sales_proxy,
       sum(fulfilled_cogs_proxy)::numeric(18,2) AS fulfilled_cogs_proxy
FROM analytics.vw_daily_sales
GROUP BY 1;

-- Weather is associated with ship date and order province, NOT precise route.
CREATE OR REPLACE VIEW analytics.vw_delivery_weather AS
SELECT s.shipment_id, s.order_id, s.carrier, s.transit_days, s.late_over_3_days,
       g.province, d.calendar_date AS ship_date,
       w.precipitation_mm, w.source AS weather_source
FROM dw.fct_shipment s
JOIN dw.dim_geography g ON g.geography_key = s.geography_key
JOIN dw.dim_date d ON d.date_key = s.ship_date_key
LEFT JOIN dw.fct_weather_daily w
       ON w.date_key = s.ship_date_key AND w.geography_key = s.geography_key;
