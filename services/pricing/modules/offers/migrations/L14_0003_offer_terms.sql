-- Existing sent deadlines and snapshots stay historical; new offers use 48 hours.
ALTER TABLE l14_offers ADD COLUMN accepted_at timestamptz;
ALTER TABLE l14_offers ADD COLUMN accepted_revision bigint CHECK(accepted_revision>0);
ALTER TABLE l14_offers ADD COLUMN availability_check_after timestamptz NOT NULL DEFAULT clock_timestamp();
CREATE INDEX l14_open_offer_check ON l14_offers(availability_check_after,id) WHERE state='open';
CREATE FUNCTION l14_sent_offer_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.listing_id,NEW.listing_revision,NEW.watch_id,NEW.buyer_id,NEW.seller_id,
     NEW.seller_organization_id,NEW.quote_id,NEW.snapshot,NEW.expires_at,NEW.created_at)
 IS DISTINCT FROM (OLD.listing_id,OLD.listing_revision,OLD.watch_id,OLD.buyer_id,OLD.seller_id,
     OLD.seller_organization_id,OLD.quote_id,OLD.snapshot,OLD.expires_at,OLD.created_at) THEN
   RAISE EXCEPTION 'sent_offer_terms_immutable' USING ERRCODE='23514';
 END IF;
 IF OLD.accepted_at IS NOT NULL AND (NEW.accepted_at,NEW.accepted_revision)
 IS DISTINCT FROM (OLD.accepted_at,OLD.accepted_revision) THEN
   RAISE EXCEPTION 'offer_acceptance_immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l14_sent_offer_terms BEFORE UPDATE ON l14_offers
 FOR EACH ROW EXECUTE FUNCTION l14_sent_offer_immutable();
