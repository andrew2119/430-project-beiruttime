ALTER TABLE auction_first_bid_intents ADD COLUMN reconcile_lease uuid;
ALTER TABLE auction_first_bid_intents ADD COLUMN reconcile_until timestamptz;
ALTER TABLE auction_first_bid_intents ADD COLUMN reconcile_after timestamptz NOT NULL DEFAULT clock_timestamp();
ALTER TABLE auction_first_bid_intents ADD COLUMN reconcile_attempts integer NOT NULL DEFAULT 0 CHECK(reconcile_attempts>=0);
CREATE INDEX l14_first_intent_pending ON auction_first_bid_intents(reconcile_after,auction_id) WHERE status='pending';
