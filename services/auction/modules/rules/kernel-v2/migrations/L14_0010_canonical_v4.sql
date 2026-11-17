-- Additive terminal and cancellation modes; retained financial outcomes stay separate.
ALTER TABLE auction_lots DROP CONSTRAINT auction_lots_mode_check;
ALTER TABLE auction_lots ADD CONSTRAINT auction_lots_mode_check CHECK(mode IN
 ('bidding','first_bid_pending','listing_edit_pending','prebid_pending','prebid_reserved',
  'cancellation_pending','cancelled','ended_legacy_review','closed_no_sale','closed_winner'));
CREATE TABLE l14_kernel_operations (
 operation_id uuid PRIMARY KEY,
 auction_id uuid NOT NULL REFERENCES auction_lots(id),
 command jsonb NOT NULL,
 receipt jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 delivered_at timestamptz
);
CREATE INDEX l14_kernel_delivery_pending ON l14_kernel_operations(created_at,operation_id)
 WHERE delivered_at IS NULL;
