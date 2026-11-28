-- Keep the original row and key so reviews and commitments still reference the
-- exact legacy economics. Only the archive marker changes; no amount is converted.
ALTER TABLE l07_quotes ADD COLUMN archived boolean NOT NULL DEFAULT false;
UPDATE l07_quotes SET archived = true
WHERE snapshot->>'currency' IS DISTINCT FROM 'USD'
   OR snapshot->>'schedule_id' IS DISTINCT FROM 'usd-v2';
ALTER TABLE l07_quotes DROP CONSTRAINT l07_quote_snapshot_binding;
ALTER TABLE l07_quotes ADD CONSTRAINT l07_quote_snapshot_binding CHECK (archived OR (
 snapshot ?& ARRAY['id','owner_id','price_minor','buyer_fee_minor','seller_commission_minor','seller_net_minor','shipping_minor','tax_minor','payable_minor','currency','sample','revision','schedule_id','minor_unit_exponent']
 AND (snapshot->>'id')::uuid=id AND (snapshot->>'owner_id')::uuid=owner_id
 AND snapshot->>'currency'='USD' AND snapshot->>'schedule_id'='usd-v2'
 AND snapshot->>'sample'='true' AND (snapshot->>'revision')::integer=revision
 AND (snapshot->>'minor_unit_exponent')::integer=2
) IS TRUE);

CREATE FUNCTION l07_protect_quote_archive() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
   IF OLD.archived OR NEW.archived THEN
     RAISE EXCEPTION 'Archived quote snapshots are immutable';
   END IF;
 ELSIF NEW.archived THEN
   RAISE EXCEPTION 'New quote snapshots must be active';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l07_quote_archive_guard BEFORE INSERT OR UPDATE ON l07_quotes
 FOR EACH ROW EXECUTE FUNCTION l07_protect_quote_archive();

-- The application connects as the non-owner role. Archive evidence is available
-- only to the database owner for recorded reconciliation, not to any route.
ALTER TABLE l07_quotes ENABLE ROW LEVEL SECURITY;
CREATE POLICY l07_active_quote ON l07_quotes USING (NOT archived);
ALTER TABLE l07_quote_reviews ENABLE ROW LEVEL SECURITY;
CREATE POLICY l07_active_quote_review ON l07_quote_reviews USING (
 EXISTS (SELECT 1 FROM l07_quotes q WHERE q.id=l07_quote_reviews.quote_id AND NOT q.archived)
);
