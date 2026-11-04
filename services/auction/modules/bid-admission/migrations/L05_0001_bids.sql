CREATE TABLE auction_bids (
 auction_id uuid NOT NULL REFERENCES auction_lots(id),
 sequence bigint NOT NULL CHECK (sequence > 0),
 operation_id uuid NOT NULL REFERENCES auction_operations(id) DEFERRABLE INITIALLY DEFERRED,
 bidder_id uuid NOT NULL,
 amount_minor bigint NOT NULL CHECK (amount_minor > 0 AND amount_minor <= 9000000000000000),
 automatic boolean NOT NULL DEFAULT false,
 received_at timestamptz NOT NULL,
 PRIMARY KEY (auction_id,sequence)
);
CREATE INDEX auction_bids_owner_idx ON auction_bids(bidder_id,auction_id);
CREATE TABLE auction_maxima (
 auction_id uuid NOT NULL REFERENCES auction_lots(id),
 bidder_id uuid NOT NULL,
 amount_minor bigint NOT NULL CHECK (amount_minor > 0 AND amount_minor <= 9000000000000000),
 sequence bigint NOT NULL CHECK (sequence > 0),
 PRIMARY KEY (auction_id,bidder_id)
);
