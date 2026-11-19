CREATE TABLE auction_prebid_operations (
 id uuid PRIMARY KEY,
 auction_id uuid NOT NULL REFERENCES auction_lots(id),
 subject_id uuid NOT NULL,
 operation_key text NOT NULL CHECK(length(operation_key) BETWEEN 1 AND 128),
 request_hash text NOT NULL,
 remote_key text NOT NULL UNIQUE,
 allocation jsonb NOT NULL,
 outcome jsonb NOT NULL,
 status text NOT NULL CHECK(status IN ('pending','succeeded','denied')),
 lease_until timestamptz,
 lease_token uuid,
 attempts integer NOT NULL DEFAULT 0,
 available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(subject_id,operation_key),
 UNIQUE(auction_id)
);
CREATE INDEX auction_prebid_pending_idx ON auction_prebid_operations(available_at) WHERE status='pending';
