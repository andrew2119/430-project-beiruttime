CREATE TABLE bid_notices (
 id uuid PRIMARY KEY,
 event_id uuid NOT NULL,
 recipient_id uuid NOT NULL,
 kind text NOT NULL CHECK (kind IN ('bid_accepted','outbid')),
 auction_id uuid NOT NULL,
 listing_id uuid NOT NULL,
 sequence bigint NOT NULL CHECK(sequence > 0),
 current_minor bigint NOT NULL CHECK(current_minor > 0 AND current_minor <= 9000000000000000),
 currency text NOT NULL CHECK(currency IN ('USD','LBP')),
 ends_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL,
 delivered_at timestamptz,
 attempts integer NOT NULL DEFAULT 0,
 available_at timestamptz NOT NULL DEFAULT now(),
 lease_token uuid,
 leased_until timestamptz,
 UNIQUE(event_id,recipient_id,kind)
);
CREATE INDEX bid_notices_recipient_idx ON bid_notices(recipient_id,created_at DESC,id);
CREATE INDEX bid_notices_due_idx ON bid_notices(available_at) WHERE delivered_at IS NULL;
