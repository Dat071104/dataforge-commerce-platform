-- Isolated P7.2 operational simulator. No accepted DataForge schema is used.
CREATE SCHEMA IF NOT EXISTS dataforge_operational;

CREATE TABLE IF NOT EXISTS dataforge_operational.orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    order_date DATE NOT NULL,
    province_id TEXT NOT NULL,
    status TEXT NOT NULL,
    order_net_amount NUMERIC(18, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS dataforge_operational.payment_events (
    payment_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    payment_date DATE NOT NULL,
    amount NUMERIC(18, 2) NOT NULL,
    status TEXT NOT NULL,
    method TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataforge_operational.change_journal (
    change_seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_identity TEXT NOT NULL CHECK (source_identity = 'dataforge-operational-v1'),
    change_id TEXT NOT NULL UNIQUE,
    source_table TEXT NOT NULL CHECK (source_table IN ('orders', 'payment_events')),
    business_key TEXT NOT NULL,
    operation CHAR(1) NOT NULL CHECK (operation IN ('I', 'U', 'D')),
    source_updated_at TIMESTAMPTZ NOT NULL,
    business_event_at TIMESTAMPTZ NOT NULL,
    schema_version SMALLINT NOT NULL CHECK (schema_version = 1),
    payload JSONB NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    event_sha256 TEXT NOT NULL CHECK (event_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS change_journal_timestamp_cursor_idx
    ON dataforge_operational.change_journal (source_updated_at, change_seq);

CREATE OR REPLACE FUNCTION dataforge_operational.reject_journal_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'dataforge_operational.change_journal is append-only';
END;
$$;

DROP TRIGGER IF EXISTS change_journal_append_only
    ON dataforge_operational.change_journal;
CREATE TRIGGER change_journal_append_only
    BEFORE UPDATE OR DELETE ON dataforge_operational.change_journal
    FOR EACH ROW EXECUTE FUNCTION dataforge_operational.reject_journal_mutation();
