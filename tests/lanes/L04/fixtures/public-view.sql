-- Frozen Catalog public-listings v1 consumer fixture; private rows never enter it.
CREATE OR REPLACE VIEW catalog_public_listings_v1 AS
 SELECT id, owner_subject_id AS seller_id, organization_id, seller_type, seller_label,
 physical_watch_id, revision, status, facts, photo_ids, cover_id, is_demo,
 registration, rules_version, published_at
 FROM catalog_listings WHERE status='published' AND NOT is_hidden;
