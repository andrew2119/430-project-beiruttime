ALTER TABLE maintenance_request_outbox
    ADD COLUMN next_attempt_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN held_at timestamptz,
    ADD COLUMN operator_id uuid,
    ADD COLUMN last_requeued_hold_at timestamptz,
    ADD COLUMN last_requeued_by uuid,
    ADD CONSTRAINT maintenance_delivery_hold_binding CHECK (
        (held_at IS NULL AND operator_id IS NULL)
        OR (held_at IS NOT NULL AND operator_id IS NOT NULL AND attempts = 8 AND delivered_at IS NULL)
    );

CREATE INDEX maintenance_delivery_due
    ON maintenance_request_outbox (next_attempt_at, event_id)
    WHERE delivered_at IS NULL AND held_at IS NULL;

CREATE INDEX maintenance_delivery_held
    ON maintenance_request_outbox (operator_id, held_at, event_id) WHERE held_at IS NOT NULL;
