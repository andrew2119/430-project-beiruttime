ALTER TABLE maintenance_request_outbox
    ADD COLUMN escalated_at timestamptz,
    ADD CONSTRAINT maintenance_delivery_escalation_time CHECK (escalated_at >= held_at);

CREATE TABLE maintenance_delivery_escalations (
    event_id uuid NOT NULL REFERENCES maintenance_request_outbox(event_id),
    held_at timestamptz NOT NULL,
    operator_id uuid NOT NULL,
    escalated_at timestamptz NOT NULL CHECK (escalated_at >= held_at),
    PRIMARY KEY (event_id, held_at)
);

CREATE INDEX maintenance_delivery_escalation_due
    ON maintenance_request_outbox (held_at, event_id)
    WHERE held_at IS NOT NULL AND escalated_at IS NULL;
