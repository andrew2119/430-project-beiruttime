-- Temporal ending never resolves a legacy financial commitment.
ALTER TABLE l13_auction_closes ADD COLUMN scheduled_ends_at timestamptz;
ALTER TABLE l13_auction_closes DROP CONSTRAINT l13_auction_closes_state_check;
ALTER TABLE l13_auction_closes ADD CONSTRAINT l13_auction_closes_state_check
 CHECK(state IN ('no_sale','allocation_pending','allocation_denied','closed','ended_legacy_review'));
ALTER TABLE l13_auction_closes DROP CONSTRAINT l13_auction_closes_close_version_check;
ALTER TABLE l13_auction_closes ADD CONSTRAINT l13_auction_closes_close_version_check
 CHECK(close_version>0 OR (state='ended_legacy_review' AND close_version=0));
ALTER TABLE l13_auction_closes ADD CONSTRAINT l13_legacy_review_no_new_sale
 CHECK(state<>'ended_legacy_review' OR (winner_id IS NULL AND order_id IS NULL AND quote_request IS NULL AND allocation_payload IS NULL));
