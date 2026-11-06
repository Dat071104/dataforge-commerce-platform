-- Use after collecting BEFORE plans. Never assert a speedup without measurement.
-- Simple demonstration index for a selective order-date predicate:
CREATE INDEX IF NOT EXISTS raw_orders_date_idx ON raw.orders(order_date);
ANALYZE raw.orders;
