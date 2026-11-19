CREATE TABLE IF NOT EXISTS l22_recovery (
  notice_id TEXT PRIMARY KEY REFERENCES l22_outbox(notice_id),
  operator TEXT NOT NULL, escalation_operator TEXT NOT NULL, next_action TEXT NOT NULL,
  held_at TEXT NOT NULL, response_due TEXT NOT NULL, escalate_at TEXT NOT NULL,
  responded_at TEXT, escalated_at TEXT, state TEXT NOT NULL, revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS l22_reconciliation (
  actor TEXT NOT NULL, operation TEXT NOT NULL, request TEXT NOT NULL, result TEXT NOT NULL,
  PRIMARY KEY(actor,operation));
