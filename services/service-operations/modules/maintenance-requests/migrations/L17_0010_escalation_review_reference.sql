ALTER TABLE maintenance_delivery_escalations
    ADD COLUMN reviewed_hold_at timestamptz,
    ADD CONSTRAINT maintenance_escalation_review_reference CHECK (
        reviewed_hold_at IS NULL OR (
            reviewed_at IS NOT NULL AND reviewed_hold_at >= held_at AND reviewed_hold_at <= reviewed_at
        )
    );

CREATE UNIQUE INDEX maintenance_escalation_review_operation
    ON maintenance_delivery_escalations (event_id, reviewed_hold_at)
    WHERE reviewed_hold_at IS NOT NULL;
