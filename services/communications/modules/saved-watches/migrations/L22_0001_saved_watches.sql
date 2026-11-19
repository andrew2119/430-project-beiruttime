CREATE TABLE IF NOT EXISTS l22_saves (
  owner TEXT NOT NULL, watch TEXT NOT NULL, revision INTEGER NOT NULL,
  saved INTEGER NOT NULL, alerts TEXT NOT NULL, PRIMARY KEY(owner,watch));
CREATE TABLE IF NOT EXISTS l22_operations (
  owner TEXT NOT NULL, operation TEXT NOT NULL, request TEXT NOT NULL,
  result TEXT NOT NULL, PRIMARY KEY(owner,operation));
CREATE TABLE IF NOT EXISTS l22_sources (
  watch TEXT PRIMARY KEY, revision INTEGER NOT NULL, snapshot TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS l22_outbox (
  notice_id TEXT PRIMARY KEY, owner TEXT NOT NULL, watch TEXT NOT NULL,
  kind TEXT NOT NULL, source_revision INTEGER NOT NULL, save_revision INTEGER NOT NULL,
  occurred_at TEXT NOT NULL, scheduled_end TEXT, sample INTEGER NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0, attempted_at TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS l22_pending_alerts ON l22_outbox(delivered,attempts,attempted_at,notice_id);
CREATE TABLE IF NOT EXISTS l22_observed_sources (
  watch TEXT PRIMARY KEY, revision INTEGER NOT NULL, snapshot TEXT NOT NULL);
INSERT OR IGNORE INTO l22_observed_sources SELECT * FROM l22_sources;
CREATE TABLE IF NOT EXISTS l22_ending_subscriptions (
  owner TEXT NOT NULL, watch TEXT NOT NULL, since_revision INTEGER NOT NULL,
  PRIMARY KEY(owner,watch));
