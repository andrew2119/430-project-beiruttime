ALTER TABLE maintenance_delivery_escalations
    ADD COLUMN reviewed_at timestamptz,
    ADD COLUMN reviewed_by uuid,
    ADD CONSTRAINT maintenance_escalation_review_binding CHECK (
        (reviewed_at IS NULL AND reviewed_by IS NULL)
        OR (reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND reviewed_at >= escalated_at)
    );
