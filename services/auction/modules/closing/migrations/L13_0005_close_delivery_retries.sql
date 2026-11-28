-- Delivery scheduling is separate from the immutable commercial decision.
CREATE TABLE l13_close_delivery_retries (
 auction_id uuid PRIMARY KEY REFERENCES auction_lots(id),
 next_attempt_at timestamptz NOT NULL
);
CREATE INDEX l13_close_delivery_retry_due ON l13_close_delivery_retries(next_attempt_at,auction_id);
