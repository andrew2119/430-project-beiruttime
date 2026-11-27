CREATE TABLE maintenance_assessment_inbox (
    event_id uuid PRIMARY KEY REFERENCES maintenance_request_outbox(event_id),
    request_id uuid NOT NULL UNIQUE REFERENCES maintenance_requests(id),
    organization_id uuid NOT NULL,
    delivered_at timestamptz NOT NULL
);

CREATE INDEX maintenance_assessment_inbox_business
    ON maintenance_assessment_inbox (organization_id, delivered_at DESC, request_id);
CREATE INDEX maintenance_request_outbox_pending
    ON maintenance_request_outbox (created_at, event_id) WHERE delivered_at IS NULL;
