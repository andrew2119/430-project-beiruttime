CREATE TABLE IF NOT EXISTS l19_work_rejections (
operation TEXT PRIMARY KEY, body TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS l19_work_jobs (
subject TEXT PRIMARY KEY, revision INTEGER NOT NULL, paused INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS l19_work_operations (
operation TEXT PRIMARY KEY, subject TEXT NOT NULL, actor TEXT NOT NULL,
organization TEXT NOT NULL, body TEXT NOT NULL, result TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS l19_work_scope ON l19_work_operations(subject, organization);
