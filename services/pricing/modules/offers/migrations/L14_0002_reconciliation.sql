ALTER TABLE l14_offers ADD COLUMN reconcile_lease uuid;
ALTER TABLE l14_offers ADD COLUMN reconcile_until timestamptz;
ALTER TABLE l14_offers ADD COLUMN reconcile_after timestamptz NOT NULL DEFAULT clock_timestamp();
ALTER TABLE l14_offers ADD COLUMN reconcile_attempts integer NOT NULL DEFAULT 0 CHECK(reconcile_attempts>=0);
CREATE INDEX l14_offer_pending ON l14_offers(reconcile_after,id) WHERE state='acceptance_pending';
