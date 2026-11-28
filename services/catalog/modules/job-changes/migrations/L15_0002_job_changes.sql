CREATE TABLE IF NOT EXISTS l15_changes (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    intent TEXT NOT NULL,
    result TEXT NOT NULL,
    approval TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
CREATE UNIQUE INDEX IF NOT EXISTS l15_one_change
    ON l15_changes(subject_id) WHERE active = 1;
CREATE TABLE IF NOT EXISTS l15_change_outbox (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
