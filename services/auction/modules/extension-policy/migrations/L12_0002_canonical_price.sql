-- Canonical kernel projection; the original settings table remains readable during rollout.
ALTER TABLE auction_lots ADD COLUMN buy_now_minor bigint CHECK(buy_now_minor>0 AND buy_now_minor<=9000000000000000);
UPDATE auction_lots l SET buy_now_minor=s.buy_now_minor FROM auction_policy_settings s WHERE s.auction_id=l.id;
CREATE FUNCTION l12_guard_buy_now_price() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.buy_now_minor IS DISTINCT FROM OLD.buy_now_minor AND
    (OLD.accepted_sequence>0 OR coalesce(to_jsonb(OLD)->>'mode','bidding')<>'bidding') THEN
   RAISE EXCEPTION 'auction_policy_frozen' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER l12_buy_now_price_frozen BEFORE UPDATE OF buy_now_minor ON auction_lots
 FOR EACH ROW EXECUTE FUNCTION l12_guard_buy_now_price();
