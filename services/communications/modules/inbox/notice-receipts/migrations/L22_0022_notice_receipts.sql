CREATE TABLE l22_notice_events (
 event_id uuid PRIMARY KEY, request_hash text NOT NULL
);
CREATE TABLE l22_payment_notice_intents (
 event_id uuid PRIMARY KEY, notice_id uuid NOT NULL UNIQUE REFERENCES l07_notices(id),
 order_id uuid NOT NULL UNIQUE, buyer_id uuid NOT NULL, source_revision integer NOT NULL CHECK(source_revision > 0),
 notified_at timestamptz NOT NULL, receipt jsonb NOT NULL,
 verified_delivery_recorded boolean NOT NULL CHECK(verified_delivery_recorded),
 acknowledged_at timestamptz, attempts integer NOT NULL DEFAULT 0,
 available_at timestamptz NOT NULL DEFAULT now(), lease_token uuid, leased_until timestamptz,
 next_actor text NOT NULL DEFAULT 'communications',
 next_review_at timestamptz NOT NULL DEFAULT now()+interval '24 hours'
);
CREATE INDEX l22_payment_notice_due ON l22_payment_notice_intents(available_at,event_id)
 WHERE acknowledged_at IS NULL;
CREATE TABLE l22_verified_notice_deliveries (
 notice_id uuid PRIMARY KEY REFERENCES l07_notices(id), buyer_id uuid NOT NULL,
 recorded_at timestamptz NOT NULL, simulated boolean NOT NULL CHECK(simulated)
);
