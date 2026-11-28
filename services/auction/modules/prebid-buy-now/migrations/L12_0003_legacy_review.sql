-- Retain every operation and original economic binding; no fence or money mutation.
CREATE FUNCTION l12_refuse_new_auction_purchase() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'auction_purchase_removed' USING ERRCODE='23514';
END;
$$;
CREATE TRIGGER l12_no_new_auction_purchase BEFORE INSERT ON auction_prebid_operations
 FOR EACH ROW EXECUTE FUNCTION l12_refuse_new_auction_purchase();
ALTER TABLE auction_prebid_operations ADD COLUMN scheduled_ends_at timestamptz;
UPDATE auction_prebid_operations p SET scheduled_ends_at=coalesce((to_jsonb(l)->>'scheduled_ends_at')::timestamptz,l.ends_at)
 FROM auction_lots l WHERE l.id=p.auction_id;
ALTER TABLE auction_prebid_operations ALTER COLUMN scheduled_ends_at SET NOT NULL;
ALTER TABLE auction_prebid_operations ADD COLUMN review_state text NOT NULL DEFAULT 'outcome_pending'
 CHECK(review_state IN ('outcome_pending','release_pending','reservation_recorded'));
ALTER TABLE auction_prebid_operations ADD COLUMN review_code text NOT NULL DEFAULT 'legacy_outcome_pending'
 CHECK(review_code IN ('legacy_outcome_pending','legacy_release_pending','legacy_conflicting_outcome','legacy_currency_review','reserved'));
ALTER TABLE auction_prebid_operations ADD COLUMN ended_review_recorded boolean NOT NULL DEFAULT false;
UPDATE auction_prebid_operations SET review_state=CASE WHEN status='denied' THEN 'release_pending'
 WHEN status='succeeded' THEN 'reservation_recorded' ELSE 'outcome_pending' END,
 review_code=CASE WHEN status='denied' THEN 'legacy_release_pending' WHEN status='succeeded' THEN 'reserved' ELSE 'legacy_outcome_pending' END;
CREATE INDEX auction_prebid_legacy_review_idx ON auction_prebid_operations(available_at)
 WHERE review_state IN ('outcome_pending','release_pending');
CREATE FUNCTION l12_keep_legacy_binding() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.id,NEW.auction_id,NEW.subject_id,NEW.operation_key,NEW.request_hash,NEW.remote_key,
     NEW.allocation,NEW.created_at,NEW.admission_revision,NEW.scheduled_ends_at)
 IS DISTINCT FROM
    (OLD.id,OLD.auction_id,OLD.subject_id,OLD.operation_key,OLD.request_hash,OLD.remote_key,
     OLD.allocation,OLD.created_at,OLD.admission_revision,OLD.scheduled_ends_at) THEN
   RAISE EXCEPTION 'legacy_purchase_binding_frozen' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER l12_legacy_binding BEFORE UPDATE ON auction_prebid_operations
 FOR EACH ROW EXECUTE FUNCTION l12_keep_legacy_binding();
