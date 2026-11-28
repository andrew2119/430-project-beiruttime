CREATE TABLE l13_auction_support_outbox (
 event_id uuid PRIMARY KEY,
 auction_id uuid NOT NULL REFERENCES l13_auction_closes(auction_id),
 result_revision bigint NOT NULL CHECK (result_revision > 0),
 facts jsonb NOT NULL,
 available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 lease_token uuid,
 lease_until timestamptz,
 delivered_at timestamptz,
 UNIQUE (auction_id, result_revision)
);
CREATE INDEX l13_auction_support_delivery_pending ON l13_auction_support_outbox (available_at, auction_id, result_revision)
 WHERE delivered_at IS NULL;

-- The still-pending cohort retains its actual original allocation hold.
INSERT INTO l13_auction_support_outbox(event_id,auction_id,result_revision,facts)
SELECT gen_random_uuid(), c.auction_id, c.result_revision,
 jsonb_build_object('schema_version',1,'auction_id',c.auction_id,'listing_id',a.listing_id,'watch_id',a.watch_id,
  'buyer_id',c.winner_id,'order_id',NULL,'result_revision',c.result_revision,'financial_revision',NULL,
  'held_since',to_char(c.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),'reason','allocation_pending')
FROM l13_auction_closes c JOIN auction_lots a ON a.id=c.auction_id
WHERE c.state='allocation_pending' AND c.order_id IS NULL AND c.winner_id IS NOT NULL AND a.currency='USD';
