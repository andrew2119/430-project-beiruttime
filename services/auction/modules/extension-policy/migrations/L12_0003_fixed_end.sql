-- Keep historic settings and commitments unchanged; refuse new obsolete settings.
CREATE FUNCTION l12_guard_fixed_end() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' THEN
   IF NEW.extension_policy<>'none.v1' OR NEW.buy_now_minor IS NOT NULL THEN
     RAISE EXCEPTION 'fixed_end_policy' USING ERRCODE='23514';
   END IF;
 ELSE
   IF (NEW.extension_policy IS DISTINCT FROM OLD.extension_policy AND NEW.extension_policy<>'none.v1')
      OR (NEW.buy_now_minor IS DISTINCT FROM OLD.buy_now_minor AND NEW.buy_now_minor IS NOT NULL) THEN
     RAISE EXCEPTION 'fixed_end_policy' USING ERRCODE='23514';
   END IF;
   IF OLD.accepted_sequence>0 AND NEW.ends_at IS DISTINCT FROM OLD.ends_at THEN
     RAISE EXCEPTION 'fixed_end_policy' USING ERRCODE='23514';
   END IF;
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER l12_fixed_end BEFORE INSERT OR UPDATE ON auction_lots
 FOR EACH ROW EXECUTE FUNCTION l12_guard_fixed_end();
