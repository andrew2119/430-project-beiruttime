-- Keep old bid history and receipts. A compatibility row is not itself a ceiling.
ALTER TABLE auction_maxima ADD COLUMN verified_ceiling boolean NOT NULL DEFAULT false;
ALTER TABLE auction_operations ADD COLUMN private_maximum_binding jsonb;
ALTER TABLE auction_lots ADD COLUMN listing_is_demo boolean;

-- The first public row of a full-step maximum is automatic and belongs to
-- its submitter. A ceiling-only raise has a receipt sequence but no public row.
-- A later manual overwrite of the maximum has a different, unverified sequence.
UPDATE auction_maxima AS m SET verified_ceiling = true
WHERE EXISTS (
 SELECT 1 FROM auction_operations AS o
 WHERE o.auction_id = m.auction_id AND o.subject_id = m.bidder_id
   AND o.organization_id IS NULL AND o.outcome->>'status' = 'succeeded'
   AND o.outcome->>'code' = 'bid_accepted' AND o.outcome->>'mode' = 'bidding'
   AND o.outcome ? 'end_version'
   AND (
    EXISTS (
     SELECT 1 FROM auction_bids AS first
     WHERE first.operation_id = o.id AND first.auction_id = m.auction_id
       AND first.bidder_id = m.bidder_id AND first.sequence = m.sequence AND first.automatic
       AND NOT EXISTS (SELECT 1 FROM auction_bids AS prev
        WHERE prev.operation_id = o.id AND prev.auction_id = m.auction_id AND prev.sequence < first.sequence)
    ) OR (
     o.outcome->>'accepted_sequence' = m.sequence::text
     AND NOT EXISTS (SELECT 1 FROM auction_bids AS b WHERE b.operation_id = o.id)
    )
   )
);

CREATE FUNCTION l06_maximum_binding_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.private_maximum_binding IS DISTINCT FROM OLD.private_maximum_binding THEN
  RAISE EXCEPTION 'auction_maximum_binding_immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l06_maximum_binding_retained BEFORE UPDATE ON auction_operations
 FOR EACH ROW EXECUTE FUNCTION l06_maximum_binding_immutable();
