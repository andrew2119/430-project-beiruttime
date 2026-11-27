-- Existing retained V2 commands keep their original transport bindings.
ALTER TABLE catalog_listing_edits
  ADD COLUMN auction_protocol smallint NOT NULL DEFAULT 2 CHECK (auction_protocol IN (2,3)),
  ADD COLUMN auction_prepared boolean NOT NULL DEFAULT false,
  ADD COLUMN auction_dispatched boolean NOT NULL DEFAULT false,
  ADD COLUMN auction_lease_seconds integer NOT NULL DEFAULT 120 CHECK (auction_lease_seconds BETWEEN 30 AND 300);
