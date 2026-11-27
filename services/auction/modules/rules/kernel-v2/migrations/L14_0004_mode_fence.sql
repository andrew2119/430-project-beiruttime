CREATE FUNCTION l14_prebid_first_commit_fence() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.mode='prebid_pending' AND (OLD.first_bid_confirmed OR OLD.accepted_sequence>0) THEN
   RAISE EXCEPTION 'first_bid_commitment_exists' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l14_prebid_first_commit BEFORE UPDATE ON auction_lots
 FOR EACH ROW EXECUTE FUNCTION l14_prebid_first_commit_fence();
