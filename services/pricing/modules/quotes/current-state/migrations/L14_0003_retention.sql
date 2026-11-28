CREATE FUNCTION l14_no_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'retained_pricing_history_immutable' USING ERRCODE='23514';
END $$;
CREATE TRIGGER l14_decision_retained BEFORE UPDATE OR DELETE ON l14_quote_decisions
 FOR EACH ROW EXECUTE FUNCTION l14_no_history_change();
CREATE TRIGGER l14_assessed_retained BEFORE DELETE ON l14_assessed_quotes
 FOR EACH ROW EXECUTE FUNCTION l14_no_history_change();
CREATE FUNCTION l14_auction_quote_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'retained_pricing_history_immutable' USING ERRCODE='23514'; END IF;
 IF (NEW.id,NEW.auction_id,NEW.buyer_id,NEW.kind,NEW.revision,NEW.snapshot,NEW.expires_at,NEW.created_at)
 IS DISTINCT FROM (OLD.id,OLD.auction_id,OLD.buyer_id,OLD.kind,OLD.revision,OLD.snapshot,OLD.expires_at,OLD.created_at)
 OR (OLD.reviewed_at IS NOT NULL AND NEW.reviewed_at IS DISTINCT FROM OLD.reviewed_at) THEN
  RAISE EXCEPTION 'retained_pricing_history_immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l14_auction_quote_retained BEFORE UPDATE OR DELETE ON l14_auction_quotes
 FOR EACH ROW EXECUTE FUNCTION l14_auction_quote_guard();
