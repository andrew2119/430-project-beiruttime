CREATE TABLE maintenance_delivery_retry_receipts (
    event_id uuid NOT NULL REFERENCES maintenance_request_outbox (event_id),
    held_at timestamptz NOT NULL,
    operator_id uuid NOT NULL,
    PRIMARY KEY (event_id, held_at)
);

INSERT INTO maintenance_delivery_retry_receipts (event_id, held_at, operator_id)
SELECT event_id, last_requeued_hold_at, last_requeued_by
FROM maintenance_request_outbox
WHERE last_requeued_hold_at IS NOT NULL AND last_requeued_by IS NOT NULL;
