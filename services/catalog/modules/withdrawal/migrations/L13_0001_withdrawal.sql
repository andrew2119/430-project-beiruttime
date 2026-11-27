ALTER TABLE catalog_listings DROP CONSTRAINT catalog_listings_status_check;
ALTER TABLE catalog_listings ADD CONSTRAINT catalog_listings_status_check CHECK(status IN ('draft','publication_pending','published','withdrawal_pending','withdrawn'));
CREATE TABLE l13_listing_withdrawals (
 id uuid PRIMARY KEY,
 listing_id uuid NOT NULL UNIQUE REFERENCES catalog_listings(id),
 actor_id uuid NOT NULL,
 organization_id uuid,
 operation_key text NOT NULL,
 base_revision bigint NOT NULL CHECK(base_revision>0),
 reason text NOT NULL CHECK(length(reason) BETWEEN 1 AND 200),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','denied','succeeded')),
 remote_payload jsonb,
 outcome jsonb,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(actor_id,operation_key)
);
CREATE TABLE l13_withdrawal_audit (
 id bigserial PRIMARY KEY,
 listing_id uuid NOT NULL REFERENCES catalog_listings(id),
 actor_id uuid NOT NULL,
 organization_id uuid,
 reason text NOT NULL,
 state text NOT NULL,
 listing_revision bigint NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
