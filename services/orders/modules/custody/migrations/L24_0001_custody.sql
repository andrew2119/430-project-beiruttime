CREATE TABLE IF NOT EXISTS l24_custody_records (
    order_id TEXT PRIMARY KEY,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS l24_custody_operations (
    operation_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    request TEXT NOT NULL,
    result TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS l24_custody_operation_order ON l24_custody_operations (order_id, revision);
CREATE TABLE IF NOT EXISTS l24_custody_outbox (
    operation_id TEXT PRIMARY KEY,
    event TEXT NOT NULL
);
