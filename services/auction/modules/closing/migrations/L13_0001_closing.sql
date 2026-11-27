-- No foreign key to future kernel columns: module order is not story dependency order.
CREATE TABLE l13_auction_closes (
 auction_id uuid PRIMARY KEY REFERENCES auction_lots(id),
 id uuid NOT NULL UNIQUE,
 end_version bigint NOT NULL CHECK(end_version>0),
 close_version bigint NOT NULL CHECK(close_version>0),
 winner_id uuid,
 closing_minor bigint NOT NULL CHECK(closing_minor>=0),
 state text NOT NULL CHECK(state IN ('no_sale','allocation_pending','allocation_denied','closed')),
 reason text,
 quote_request jsonb,
 allocation_payload jsonb,
 order_id uuid UNIQUE,
 lease uuid,
 lease_until timestamptz,
 next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 attempts integer NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX l13_closes_pending ON l13_auction_closes(next_attempt_at) WHERE state='allocation_pending';
