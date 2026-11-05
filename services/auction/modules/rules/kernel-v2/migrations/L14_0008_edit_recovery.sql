ALTER TABLE auction_listing_edits DROP CONSTRAINT auction_listing_edits_state_check;
DO $$ DECLARE c record; BEGIN
 FOR c IN SELECT conname FROM pg_constraint WHERE conrelid='auction_listing_edits'::regclass
  AND contype='c' AND pg_get_constraintdef(oid) LIKE '%commit_result%'
 LOOP EXECUTE format('ALTER TABLE auction_listing_edits DROP CONSTRAINT %I',c.conname); END LOOP;
END $$;
ALTER TABLE auction_listing_edits
 ADD COLUMN protocol integer NOT NULL DEFAULT 2 CHECK(protocol IN (2,3)),
 ADD COLUMN orders_operation_key text CHECK(length(orders_operation_key) BETWEEN 1 AND 100),
 ADD COLUMN orders_expected_revision bigint CHECK(orders_expected_revision>0),
 ADD COLUMN lease_seconds integer CHECK(lease_seconds BETWEEN 30 AND 300),
 ADD COLUMN expires_at timestamptz,
 ADD COLUMN dispatched_at timestamptz,
 ADD COLUMN dispatch_result jsonb,
 ADD COLUMN aborted_at timestamptz,
 ADD COLUMN abort_result jsonb,
 ADD COLUMN reconcile_after timestamptz NOT NULL DEFAULT clock_timestamp(),
 ADD COLUMN reconcile_lease uuid,
 ADD COLUMN reconcile_until timestamptz,
 ADD COLUMN reconcile_attempts integer NOT NULL DEFAULT 0,
 ADD CONSTRAINT auction_listing_edits_state_check CHECK(state IN ('prepared','committed','aborted')),
 ADD CONSTRAINT l14_edit_protocol CHECK(protocol=2 OR
  (orders_operation_key IS NOT NULL AND orders_expected_revision IS NOT NULL AND expires_at IS NOT NULL AND lease_seconds IS NOT NULL)),
 ADD CONSTRAINT l14_edit_dispatch CHECK((dispatched_at IS NULL)=(dispatch_result IS NULL)),
 ADD CONSTRAINT l14_edit_terminal CHECK(
  (state='prepared' AND commit_result IS NULL AND committed_at IS NULL AND abort_result IS NULL AND aborted_at IS NULL) OR
  (state='committed' AND commit_result IS NOT NULL AND committed_at IS NOT NULL AND abort_result IS NULL AND aborted_at IS NULL) OR
  (state='aborted' AND commit_result IS NULL AND committed_at IS NULL AND abort_result IS NOT NULL AND aborted_at IS NOT NULL));
CREATE INDEX l14_listing_edit_reconcile ON auction_listing_edits(reconcile_after,operation_id) WHERE state='prepared';
CREATE OR REPLACE FUNCTION l14_listing_edit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'listing_edit_intent_immutable' USING ERRCODE='23514'; END IF;
 IF (NEW.operation_id,NEW.listing_id,NEW.watch_id,NEW.listing_revision,NEW.next_revision,NEW.facts_digest,
     NEW.auction_id,NEW.prepare_result,NEW.prepared_at,NEW.protocol,NEW.orders_operation_key,
     NEW.orders_expected_revision,NEW.lease_seconds,NEW.expires_at)
 IS DISTINCT FROM (OLD.operation_id,OLD.listing_id,OLD.watch_id,OLD.listing_revision,OLD.next_revision,OLD.facts_digest,
     OLD.auction_id,OLD.prepare_result,OLD.prepared_at,OLD.protocol,OLD.orders_operation_key,
     OLD.orders_expected_revision,OLD.lease_seconds,OLD.expires_at)
 OR (OLD.refence_command IS NOT NULL AND NEW.refence_command IS DISTINCT FROM OLD.refence_command)
 OR (OLD.dispatch_result IS NOT NULL AND (NEW.dispatch_result,NEW.dispatched_at) IS DISTINCT FROM (OLD.dispatch_result,OLD.dispatched_at))
 OR (OLD.state IN ('committed','aborted') AND NEW IS DISTINCT FROM OLD) THEN
  RAISE EXCEPTION 'listing_edit_intent_immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
