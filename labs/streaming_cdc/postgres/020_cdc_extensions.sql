-- Test-only event time field used by the Week 8 watermark exercise.
ALTER TABLE dataforge_operational.orders
    ADD COLUMN IF NOT EXISTS event_time TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp();

-- Preserve complete before-images for Debezium updates and deletes.
ALTER TABLE dataforge_operational.orders REPLICA IDENTITY FULL;
ALTER TABLE dataforge_operational.payment_events REPLICA IDENTITY FULL;
ALTER TABLE dataforge_operational.change_journal REPLICA IDENTITY FULL;

INSERT INTO dataforge_operational.orders (
    order_id,
    customer_id,
    order_date,
    province_id,
    status,
    order_net_amount,
    event_time
)
VALUES
    ('w8-seed-001', 'customer-001', CURRENT_DATE, 'province-01', 'paid', 120.00, clock_timestamp() - INTERVAL '2 minutes'),
    ('w8-seed-002', 'customer-002', CURRENT_DATE, 'province-02', 'paid', 75.50, clock_timestamp() - INTERVAL '1 minute')
ON CONFLICT (order_id) DO NOTHING;

INSERT INTO dataforge_operational.payment_events (
    payment_id,
    order_id,
    payment_date,
    amount,
    status,
    method
)
VALUES (
    'w8-payment-seed-001',
    'w8-seed-001',
    CURRENT_DATE,
    120.00,
    'settled',
    'local-test'
)
ON CONFLICT (payment_id) DO NOTHING;

INSERT INTO dataforge_operational.change_journal (
    source_identity,
    change_id,
    source_table,
    business_key,
    operation,
    source_updated_at,
    business_event_at,
    schema_version,
    payload,
    payload_sha256,
    event_sha256
)
VALUES (
    'dataforge-operational-v1',
    'w8-cdc-seed-001',
    'orders',
    'w8-seed-001',
    'I',
    clock_timestamp(),
    clock_timestamp(),
    1,
    '{"order_id":"w8-seed-001","status":"paid","amount":"120.00"}'::jsonb,
    repeat('a', 64),
    repeat('b', 64)
)
ON CONFLICT (change_id) DO NOTHING;
