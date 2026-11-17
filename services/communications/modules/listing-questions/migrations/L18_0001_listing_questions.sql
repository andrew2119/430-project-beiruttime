CREATE TABLE IF NOT EXISTS l18_questions (
  id TEXT PRIMARY KEY, listing TEXT NOT NULL, watch TEXT NOT NULL,
  author TEXT NOT NULL, seller TEXT NOT NULL, question TEXT NOT NULL, normalized TEXT NOT NULL,
  answer TEXT, state TEXT NOT NULL, revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS l18_receipts (
  operation TEXT PRIMARY KEY, binding TEXT NOT NULL, result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS l18_reports (
  operation TEXT PRIMARY KEY, question TEXT NOT NULL, reporter TEXT NOT NULL,
  reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS l18_appeals (
  operation TEXT PRIMARY KEY, question TEXT NOT NULL, actor TEXT NOT NULL,
  reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS l18_audit (
  operation TEXT PRIMARY KEY, actor TEXT NOT NULL, question TEXT NOT NULL,
  reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS l18_outbox (
  operation TEXT PRIMARY KEY, payload TEXT NOT NULL);

CREATE INDEX IF NOT EXISTS l18_questions_public ON l18_questions(listing,watch,state,id);
CREATE INDEX IF NOT EXISTS l18_questions_matching ON l18_questions(listing,watch,state,normalized,id);
CREATE INDEX IF NOT EXISTS l18_reports_question ON l18_reports(question,reporter);
CREATE INDEX IF NOT EXISTS l18_appeals_question ON l18_appeals(question,created_at);
