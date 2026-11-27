ALTER TABLE auction_lots ADD COLUMN listing_revision bigint NOT NULL DEFAULT 1 CHECK(listing_revision>0);
ALTER TABLE auction_lots ADD COLUMN scheduled_ends_at timestamptz;
UPDATE auction_lots SET scheduled_ends_at=ends_at;
ALTER TABLE auction_lots ALTER COLUMN scheduled_ends_at SET NOT NULL;
CREATE FUNCTION l14_schedule_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' THEN
   NEW.scheduled_ends_at=coalesce(NEW.scheduled_ends_at,NEW.ends_at);
   RETURN NEW;
 END IF;
 IF OLD.accepted_sequence=0 AND NEW.accepted_sequence=0 AND NEW.ends_at IS DISTINCT FROM OLD.ends_at THEN
   NEW.scheduled_ends_at=NEW.ends_at;
 END IF;
 IF OLD.accepted_sequence>0 AND (NEW.scheduled_ends_at,NEW.listing_revision)
 IS DISTINCT FROM (OLD.scheduled_ends_at,OLD.listing_revision) THEN
   RAISE EXCEPTION 'auction_source_schedule_frozen' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l14_original_schedule BEFORE INSERT OR UPDATE ON auction_lots
 FOR EACH ROW EXECUTE FUNCTION l14_schedule_frozen();
