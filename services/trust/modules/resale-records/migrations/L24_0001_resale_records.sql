CREATE TABLE IF NOT EXISTS l24_transfers (
 operation TEXT PRIMARY KEY, binding TEXT NOT NULL, actor TEXT NOT NULL,
 organization TEXT NOT NULL, subject TEXT NOT NULL, watch TEXT NOT NULL,
 sale TEXT NOT NULL UNIQUE, result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS l24_history (
 watch TEXT NOT NULL, revision INTEGER NOT NULL, summary TEXT NOT NULL,
 PRIMARY KEY(watch, revision));
CREATE TABLE IF NOT EXISTS l24_outbox (
 event TEXT PRIMARY KEY, payload TEXT NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS l24_requests (
 operation TEXT PRIMARY KEY, binding TEXT NOT NULL, started_at TEXT NOT NULL,
 responsible_operator TEXT NOT NULL);
