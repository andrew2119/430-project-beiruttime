CREATE TABLE catalog_listing_edits (
 id uuid PRIMARY KEY, listing_id uuid NOT NULL REFERENCES catalog_listings(id),
 actor_id uuid NOT NULL, organization_id uuid, operation_key text NOT NULL,
 digest text NOT NULL, base_revision integer NOT NULL, facts jsonb NOT NULL,
 reason text NOT NULL, status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','committed','succeeded','denied')),
 orders_revision integer, orders_started boolean NOT NULL DEFAULT false, result jsonb, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(listing_id,actor_id,operation_key)
);
CREATE UNIQUE INDEX catalog_listing_one_edit ON catalog_listing_edits(listing_id) WHERE status IN ('pending','committed');
CREATE TABLE catalog_listing_history (
 listing_id uuid NOT NULL REFERENCES catalog_listings(id), revision integer NOT NULL,
 actor_id uuid NOT NULL, reason text NOT NULL, before_facts jsonb NOT NULL, after_facts jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(listing_id,revision)
);
