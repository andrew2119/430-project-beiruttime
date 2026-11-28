ALTER TABLE auction_lots DROP CONSTRAINT auction_lots_mode_check;
ALTER TABLE auction_lots ADD CONSTRAINT auction_lots_mode_check CHECK(mode IN
 ('bidding','first_bid_pending','listing_edit_pending','prebid_pending','prebid_reserved','closed_no_sale','closed_winner'));
CREATE TABLE auction_listing_edits (
 operation_id uuid PRIMARY KEY, listing_id uuid NOT NULL, watch_id uuid NOT NULL,
 listing_revision bigint NOT NULL CHECK(listing_revision>0), next_revision bigint NOT NULL,
 facts_digest text NOT NULL CHECK(facts_digest ~ '^[a-f0-9]{64}$'),
 auction_id uuid REFERENCES auction_lots(id), state text NOT NULL DEFAULT 'prepared' CHECK(state IN ('prepared','committed')),
 prepare_result jsonb NOT NULL, commit_result jsonb, refence_command jsonb,
 prepared_at timestamptz NOT NULL DEFAULT clock_timestamp(), committed_at timestamptz,
 CHECK(next_revision=listing_revision+1),
 CHECK((state='prepared' AND commit_result IS NULL AND committed_at IS NULL)
    OR (state='committed' AND commit_result IS NOT NULL AND committed_at IS NOT NULL))
);
CREATE UNIQUE INDEX l14_listing_edit_active ON auction_listing_edits(listing_id) WHERE state='prepared';
CREATE FUNCTION l14_listing_edit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'listing_edit_intent_immutable' USING ERRCODE='23514'; END IF;
 IF (NEW.operation_id,NEW.listing_id,NEW.watch_id,NEW.listing_revision,NEW.next_revision,NEW.facts_digest,
     NEW.auction_id,NEW.prepare_result,NEW.prepared_at)
 IS DISTINCT FROM (OLD.operation_id,OLD.listing_id,OLD.watch_id,OLD.listing_revision,OLD.next_revision,OLD.facts_digest,
     OLD.auction_id,OLD.prepare_result,OLD.prepared_at)
 OR (OLD.refence_command IS NOT NULL AND NEW.refence_command IS DISTINCT FROM OLD.refence_command)
 OR (OLD.state='committed' AND NEW IS DISTINCT FROM OLD) THEN
  RAISE EXCEPTION 'listing_edit_intent_immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l14_listing_edit_retained BEFORE UPDATE OR DELETE ON auction_listing_edits
 FOR EACH ROW EXECUTE FUNCTION l14_listing_edit_immutable();
