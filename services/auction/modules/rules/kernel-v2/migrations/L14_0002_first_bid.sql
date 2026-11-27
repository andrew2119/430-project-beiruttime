-- Durable remote first-bid fence intent. Pending is not a bid or a winner.
ALTER TABLE auction_lots DROP CONSTRAINT auction_lots_mode_check;
ALTER TABLE auction_lots ADD CONSTRAINT auction_lots_mode_check CHECK(mode IN
 ('bidding','first_bid_pending','prebid_pending','prebid_reserved','closed_no_sale','closed_winner'));
ALTER TABLE auction_lots ADD COLUMN first_bid_confirmed boolean NOT NULL DEFAULT false;
CREATE TABLE auction_first_bid_intents (
 auction_id uuid PRIMARY KEY REFERENCES auction_lots(id), subject_id uuid NOT NULL,
 operation_key text NOT NULL, request_hash text NOT NULL, command jsonb NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','succeeded','denied')),
 outcome jsonb, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
