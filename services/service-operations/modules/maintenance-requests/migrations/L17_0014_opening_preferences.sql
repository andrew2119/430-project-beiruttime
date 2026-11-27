CREATE TABLE maintenance_opening_preferences (
    operation_id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES maintenance_requests(id),
    revision integer NOT NULL CHECK (revision > 0),
    receipt jsonb NOT NULL,
    UNIQUE (request_id,revision)
);
CREATE TABLE maintenance_opening_acknowledgements (
    operation_id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES maintenance_requests(id),
    consent_revision integer NOT NULL CHECK (consent_revision > 0),
    receipt jsonb NOT NULL,
    UNIQUE (request_id,consent_revision),
    FOREIGN KEY (request_id,consent_revision) REFERENCES maintenance_opening_preferences(request_id,revision)
);
