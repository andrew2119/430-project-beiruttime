ALTER TABLE catalog_listings ADD COLUMN is_hidden boolean NOT NULL DEFAULT false;
ALTER TABLE catalog_listings ADD CONSTRAINT catalog_cover_in_gallery
 CHECK (cover_id IS NULL OR cover_id=ANY(photo_ids));
ALTER TABLE catalog_listings ADD CONSTRAINT catalog_publication_has_proof
 CHECK (status<>'published' OR (registration IS NOT NULL AND fee_snapshot IS NOT NULL
 AND rules_version IS NOT NULL AND published_at IS NOT NULL AND cover_id IS NOT NULL AND cardinality(photo_ids)>0));
CREATE TABLE catalog_moderation_cases (
 case_id uuid PRIMARY KEY,
 listing_id uuid NOT NULL REFERENCES catalog_listings(id),
 revision integer NOT NULL CHECK(revision>0),
 hidden boolean NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX catalog_moderation_cases_target ON catalog_moderation_cases(listing_id) WHERE hidden;
CREATE OR REPLACE VIEW catalog_public_listings_v1 AS
 SELECT id, owner_subject_id AS seller_id, organization_id, seller_type, seller_label,
 physical_watch_id, revision, status, facts, photo_ids, cover_id, is_demo,
 registration, rules_version, published_at
 FROM catalog_listings WHERE status='published' AND NOT is_hidden;
