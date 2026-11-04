CREATE TABLE catalog_listings (
 id uuid PRIMARY KEY,
 owner_subject_id uuid NOT NULL,
 organization_id uuid,
 seller_type text NOT NULL CHECK (seller_type IN ('private','dealer','brand')),
 seller_label text NOT NULL,
 physical_watch_id uuid NOT NULL UNIQUE,
 revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
 status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','publication_pending','published')),
 facts jsonb NOT NULL DEFAULT '{}'::jsonb,
 photo_ids uuid[] NOT NULL DEFAULT '{}',
 cover_id uuid,
 is_demo boolean NOT NULL DEFAULT false,
 demo_key text UNIQUE,
 registration jsonb,
 fee_snapshot jsonb,
 rules_version text,
 published_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK ((is_demo AND demo_key IS NOT NULL) OR (NOT is_demo AND demo_key IS NULL))
);
CREATE INDEX catalog_listings_owner ON catalog_listings(owner_subject_id,updated_at DESC,id);
CREATE INDEX catalog_listings_org ON catalog_listings(organization_id,updated_at DESC,id) WHERE organization_id IS NOT NULL;
CREATE INDEX catalog_listings_public ON catalog_listings(published_at DESC,id) WHERE status='published';
CREATE TABLE catalog_commands (
 scope text NOT NULL,
 operation_key text NOT NULL CHECK (length(operation_key) BETWEEN 1 AND 128),
 digest text NOT NULL,
 response jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(scope,operation_key)
);
CREATE TABLE catalog_publications (
 id uuid PRIMARY KEY,
 listing_id uuid NOT NULL UNIQUE REFERENCES catalog_listings(id),
 actor_id uuid NOT NULL,
 base_revision integer NOT NULL,
 request jsonb NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','succeeded')),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE VIEW catalog_public_listings_v1 AS
 SELECT id, owner_subject_id AS seller_id, organization_id, seller_type, seller_label,
 physical_watch_id, revision, status, facts, photo_ids, cover_id, is_demo,
 registration, rules_version, published_at
 FROM catalog_listings WHERE status='published';
