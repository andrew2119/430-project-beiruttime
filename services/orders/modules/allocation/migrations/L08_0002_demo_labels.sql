-- Sample-content provenance comes only from the publishing Catalog authority.
ALTER TABLE l08_watches ADD COLUMN is_demo boolean NOT NULL DEFAULT false;
ALTER TABLE l08_orders ADD COLUMN listing_id uuid;
ALTER TABLE l08_orders ADD COLUMN is_demo boolean NOT NULL DEFAULT false;
UPDATE l08_orders o SET listing_id=w.listing_id,is_demo=w.is_demo FROM l08_watches w WHERE w.id=o.watch_id;
ALTER TABLE l08_orders ALTER COLUMN listing_id SET NOT NULL;
