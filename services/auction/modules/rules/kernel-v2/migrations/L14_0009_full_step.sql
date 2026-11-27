-- Freeze admission while moving current private state to full-step competition.
LOCK TABLE auction_lots, auction_maxima, auction_bids IN ACCESS EXCLUSIVE MODE;
CREATE TABLE l14_auction_rule_archive (
 auction_id uuid PRIMARY KEY, snapshot jsonb NOT NULL,
 archived_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO l14_auction_rule_archive(auction_id,snapshot)
 SELECT id,to_jsonb(auction_lots) FROM auction_lots;
ALTER TABLE auction_maxima ADD COLUMN active boolean NOT NULL DEFAULT false;
UPDATE auction_maxima m SET active=true FROM auction_lots l
 WHERE m.auction_id=l.id AND m.bidder_id=l.leader_id;
CREATE UNIQUE INDEX auction_one_active_ceiling ON auction_maxima(auction_id) WHERE active;
ALTER TABLE auction_bids ADD COLUMN public_rule_version text NOT NULL DEFAULT 'ordinary.v1';
ALTER TABLE auction_lots ADD COLUMN private_state_version text NOT NULL DEFAULT 'full-step.v2';

-- Retain the former timing in the archive; future admission uses the original end.
DROP TRIGGER auction_frozen_economics ON auction_lots;
UPDATE auction_lots SET ends_at=scheduled_ends_at,
 end_version=end_version+CASE WHEN ends_at<>scheduled_ends_at THEN 1 ELSE 0 END,
 revision=revision+1 WHERE ends_at<>scheduled_ends_at;
CREATE OR REPLACE FUNCTION guard_auction_economics() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.mode='prebid_pending' AND OLD.mode<>'prebid_pending' THEN
   RAISE EXCEPTION 'auction_purchase_disabled' USING ERRCODE='23514';
 END IF;
 IF OLD.accepted_sequence>0 AND
    (NEW.currency,NEW.opening_minor,NEW.reserve_minor,NEW.increment_bands,NEW.starts_at,
     NEW.ends_at,NEW.scheduled_ends_at,NEW.rules_version,NEW.extension_policy,NEW.high_value_minor)
    IS DISTINCT FROM
    (OLD.currency,OLD.opening_minor,OLD.reserve_minor,OLD.increment_bands,OLD.starts_at,
     OLD.ends_at,OLD.scheduled_ends_at,OLD.rules_version,OLD.extension_policy,OLD.high_value_minor) THEN
   RAISE EXCEPTION 'auction_economics_frozen' USING ERRCODE='23514';
 END IF;
 IF NEW.ends_at<>NEW.scheduled_ends_at THEN
   RAISE EXCEPTION 'auction_fixed_end' USING ERRCODE='23514';
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
 IF NEW.accepted_sequence>OLD.accepted_sequence AND
    (OLD.currency<>'USD' OR NEW.current_minor>9000000000000) THEN
   RAISE EXCEPTION 'auction_legacy_reconciliation' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER auction_frozen_economics BEFORE UPDATE ON auction_lots
 FOR EACH ROW EXECUTE FUNCTION guard_auction_economics();
