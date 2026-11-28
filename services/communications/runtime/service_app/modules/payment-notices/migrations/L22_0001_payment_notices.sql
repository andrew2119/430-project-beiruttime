CREATE TABLE l22_payment_notices (
 event_id uuid PRIMARY KEY,
 order_id uuid NOT NULL UNIQUE,
 buyer_id uuid NOT NULL,
 order_revision integer NOT NULL CHECK (order_revision > 0),
 fingerprint text NOT NULL,
 notice_id uuid NOT NULL UNIQUE REFERENCES l07_notices(id),
 notified_at timestamptz NOT NULL,
 contact_revision integer,
 channel text CHECK (channel IN ('email','phone')),
 recipient_digest text,
 synthetic boolean NOT NULL DEFAULT true CHECK (synthetic),
 verified_delivery_recorded boolean NOT NULL DEFAULT false,
 acknowledged_at timestamptz,
 attempts integer NOT NULL DEFAULT 0,
 available_at timestamptz NOT NULL DEFAULT now(),
 lease_token uuid,
 leased_until timestamptz,
 CHECK (NOT verified_delivery_recorded OR
   (contact_revision > 0 AND channel IS NOT NULL AND recipient_digest IS NOT NULL))
);
CREATE INDEX l22_payment_notice_pending ON l22_payment_notices(available_at,event_id)
 WHERE acknowledged_at IS NULL;
