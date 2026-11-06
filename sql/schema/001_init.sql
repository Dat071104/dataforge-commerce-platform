CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS dw;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS raw.geography (
  province_id TEXT PRIMARY KEY, province TEXT NOT NULL, region TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw.customers (
  customer_id TEXT PRIMARY KEY, signup_date DATE NOT NULL,
  province_id TEXT NOT NULL, segment TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw.customer_segments (
  customer_id TEXT NOT NULL, segment TEXT NOT NULL,
  valid_from DATE NOT NULL, valid_to DATE,
  PRIMARY KEY (customer_id, valid_from),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE TABLE IF NOT EXISTS raw.products (
  product_id TEXT PRIMARY KEY, category TEXT NOT NULL,
  subcategory TEXT NOT NULL, base_price NUMERIC(18,2) NOT NULL,
  unit_cogs NUMERIC(18,2) NOT NULL
);
CREATE TABLE IF NOT EXISTS raw.orders (
  order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
  order_date DATE NOT NULL, province_id TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw.order_items (
  order_item_id TEXT PRIMARY KEY, order_id TEXT NOT NULL,
  product_id TEXT NOT NULL, quantity INTEGER NOT NULL,
  unit_price NUMERIC(18,2) NOT NULL, discount_pct NUMERIC(8,4) NOT NULL
);
CREATE TABLE IF NOT EXISTS raw.payments (
  payment_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, payment_date DATE NOT NULL,
  amount NUMERIC(18,2) NOT NULL, status TEXT NOT NULL, method TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw.shipments (
  shipment_id TEXT PRIMARY KEY, order_id TEXT NOT NULL,
  ship_date DATE NOT NULL, delivery_date DATE, status TEXT NOT NULL, carrier TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw.returns (
  return_id TEXT PRIMARY KEY, order_item_id TEXT NOT NULL,
  return_date DATE NOT NULL, refund_amount NUMERIC(18,2) NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw.inventory (
  snapshot_date DATE NOT NULL, product_id TEXT NOT NULL,
  quantity_in_stock INTEGER NOT NULL, reorder_point INTEGER NOT NULL,
  PRIMARY KEY (snapshot_date, product_id)
);
CREATE TABLE IF NOT EXISTS raw.weather_daily (
  province_id TEXT NOT NULL, observation_date DATE NOT NULL,
  precipitation_mm NUMERIC(12,3), temp_max_c NUMERIC(8,2), source TEXT NOT NULL,
  PRIMARY KEY (province_id, observation_date)
);
CREATE TABLE IF NOT EXISTS audit.load_runs (
  run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  row_count BIGINT NOT NULL,
  operation TEXT NOT NULL,
  rows_inserted BIGINT NOT NULL DEFAULT 0,
  rows_updated BIGINT NOT NULL DEFAULT 0,
  rows_deleted BIGINT NOT NULL DEFAULT 0,
  UNIQUE (source, sha256, operation)
);

-- Safe additive migration for databases initialized by the original baseline.
ALTER TABLE audit.load_runs
  ADD COLUMN IF NOT EXISTS rows_inserted BIGINT NOT NULL DEFAULT 0;
ALTER TABLE audit.load_runs
  ADD COLUMN IF NOT EXISTS rows_updated BIGINT NOT NULL DEFAULT 0;
ALTER TABLE audit.load_runs
  ADD COLUMN IF NOT EXISTS rows_deleted BIGINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS audit.dimension_key_state (
  dimension_name TEXT PRIMARY KEY,
  last_key BIGINT NOT NULL CHECK (last_key >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
