CREATE TABLE finish_consents (
    subject_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision > 0),
    request TEXT NOT NULL,
    source_snapshot TEXT NOT NULL
);
CREATE TABLE finish_receipts (
    operation_id TEXT PRIMARY KEY,
    request TEXT NOT NULL,
    response TEXT NOT NULL,
    source_snapshot TEXT NOT NULL
);
CREATE TABLE finish_outbox (
    event_id TEXT PRIMARY KEY REFERENCES finish_receipts(operation_id),
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL
);
