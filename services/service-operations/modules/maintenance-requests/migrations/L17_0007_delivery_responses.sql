CREATE TABLE maintenance_delivery_responses (
    event_id uuid NOT NULL REFERENCES maintenance_request_outbox(event_id),
    held_at timestamptz NOT NULL,
    operator_id uuid NOT NULL,
    responded_at timestamptz NOT NULL CHECK (responded_at >= held_at),
    PRIMARY KEY (event_id, held_at)
);
