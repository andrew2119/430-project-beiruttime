CREATE TABLE IF NOT EXISTS l22_email (
    operation TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    organization TEXT NOT NULL,
    event TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    command TEXT NOT NULL,
    recipient_revision INTEGER NOT NULL CHECK (recipient_revision > 0),
    state TEXT NOT NULL CHECK (state IN ('captured','possibly_sent','recorded','failed')),
    attempt TEXT,
    available TEXT NOT NULL,
    review TEXT,
    content TEXT NOT NULL,
    subject TEXT NOT NULL,
    UNIQUE(actor,organization,event)
)
