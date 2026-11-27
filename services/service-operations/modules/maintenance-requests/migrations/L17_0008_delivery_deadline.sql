ALTER TABLE maintenance_request_outbox ADD COLUMN escalation_started_at timestamptz;

WITH history AS (
    SELECT event_id, min(held_at) AS first_hold, min(escalated_at) AS first_escalation
    FROM maintenance_delivery_escalations
    GROUP BY event_id
)
UPDATE maintenance_request_outbox o
SET escalation_started_at = LEAST(o.held_at, o.last_requeued_hold_at, h.first_hold),
    escalated_at = COALESCE(h.first_escalation, o.escalated_at)
FROM (SELECT event_id FROM maintenance_request_outbox) AS events
LEFT JOIN history h USING (event_id)
WHERE o.event_id = events.event_id;

ALTER TABLE maintenance_request_outbox
    DROP CONSTRAINT maintenance_delivery_escalation_time,
    ADD CONSTRAINT maintenance_delivery_deadline_binding CHECK (
        (held_at IS NULL OR (escalation_started_at IS NOT NULL AND escalation_started_at <= held_at))
        AND (escalated_at IS NULL OR (escalation_started_at IS NOT NULL AND escalated_at >= escalation_started_at))
    );

DROP INDEX maintenance_delivery_escalation_due;
CREATE INDEX maintenance_delivery_deadline_due
    ON maintenance_request_outbox (escalation_started_at, event_id)
    WHERE delivered_at IS NULL AND escalation_started_at IS NOT NULL AND escalated_at IS NULL;
