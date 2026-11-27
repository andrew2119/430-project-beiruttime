ALTER TABLE bid_notices ADD COLUMN source_revision bigint CHECK (source_revision > 0);
CREATE INDEX bid_notices_outbid_occurrence_idx ON bid_notices(auction_id, sequence, recipient_id)
 WHERE kind='outbid';
