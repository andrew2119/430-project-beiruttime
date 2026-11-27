-- Additive upgrade: canonical current end and mode, shared by all auction modules.
ALTER TABLE auction_lots ADD COLUMN end_version bigint NOT NULL DEFAULT 1 CHECK(end_version>0);
ALTER TABLE auction_lots ADD COLUMN close_version bigint NOT NULL DEFAULT 0 CHECK(close_version>=0);
ALTER TABLE auction_lots ADD COLUMN mode text NOT NULL DEFAULT 'bidding'
 CHECK(mode IN ('bidding','prebid_pending','prebid_reserved','closed_no_sale','closed_winner'));
CREATE OR REPLACE FUNCTION guard_auction_economics() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.accepted_sequence>0 AND
    (NEW.currency,NEW.opening_minor,NEW.reserve_minor,NEW.increment_bands,NEW.starts_at,
     NEW.rules_version,NEW.extension_policy,NEW.high_value_minor)
    IS DISTINCT FROM
    (OLD.currency,OLD.opening_minor,OLD.reserve_minor,OLD.increment_bands,OLD.starts_at,
     OLD.rules_version,OLD.extension_policy,OLD.high_value_minor) THEN
   RAISE EXCEPTION 'auction_economics_frozen' USING ERRCODE='23514';
 END IF;
 -- A post-bid extension is sanctioned only as part of an admitted bid receipt.
 IF OLD.accepted_sequence>0 AND NEW.ends_at IS DISTINCT FROM OLD.ends_at AND NOT
    (OLD.mode='bidding' AND NEW.mode='bidding' AND NEW.ends_at>OLD.ends_at
     AND NEW.ends_at<=OLD.ends_at+interval '120 seconds'
     AND NEW.end_version=OLD.end_version+1 AND NEW.accepted_sequence>OLD.accepted_sequence
     AND NEW.revision=OLD.revision+1) THEN
   RAISE EXCEPTION 'auction_extension_not_atomic' USING ERRCODE='23514';
 END IF;
 IF (NEW.ends_at IS DISTINCT FROM OLD.ends_at AND NEW.end_version<>OLD.end_version+1)
    OR (NEW.ends_at IS NOT DISTINCT FROM OLD.ends_at AND NEW.end_version<>OLD.end_version)
    OR NEW.accepted_sequence<OLD.accepted_sequence OR NEW.revision<OLD.revision
    OR NEW.close_version<OLD.close_version THEN
   RAISE EXCEPTION 'auction_revision_monotonic' USING ERRCODE='23514';
 END IF;
 IF OLD.mode<>'bidding' AND NEW.accepted_sequence<>OLD.accepted_sequence THEN
   RAISE EXCEPTION 'auction_mode_fenced' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$$;
