ALTER TABLE auction_lots ADD CONSTRAINT auction_leader_price_consistent CHECK (
 (accepted_sequence=0 AND leader_id IS NULL AND current_minor=0)
 OR (accepted_sequence>0 AND leader_id IS NOT NULL AND current_minor>=opening_minor)
);
CREATE FUNCTION guard_auction_economics() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.accepted_sequence>0 AND
    (NEW.currency,NEW.opening_minor,NEW.reserve_minor,NEW.increment_bands,NEW.starts_at,
     NEW.ends_at,NEW.rules_version,NEW.extension_policy,NEW.high_value_minor)
    IS DISTINCT FROM
    (OLD.currency,OLD.opening_minor,OLD.reserve_minor,OLD.increment_bands,OLD.starts_at,
     OLD.ends_at,OLD.rules_version,OLD.extension_policy,OLD.high_value_minor) THEN
   RAISE EXCEPTION 'auction_economics_frozen' USING ERRCODE='23514';
 END IF;
 IF NEW.accepted_sequence<OLD.accepted_sequence OR NEW.revision<OLD.revision THEN
   RAISE EXCEPTION 'auction_revision_monotonic' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER auction_frozen_economics BEFORE UPDATE ON auction_lots
 FOR EACH ROW EXECUTE FUNCTION guard_auction_economics();
