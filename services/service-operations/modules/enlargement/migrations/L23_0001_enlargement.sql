CREATE TABLE IF NOT EXISTS l23_enlargement_records(id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS l23_enlargement_receipts(operation TEXT PRIMARY KEY, digest TEXT NOT NULL, actor TEXT NOT NULL, result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS l23_enlargement_outbox(operation TEXT PRIMARY KEY, body TEXT NOT NULL);
