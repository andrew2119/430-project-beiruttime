CREATE TABLE l14_offers (
 id uuid PRIMARY KEY, listing_id uuid NOT NULL, listing_revision bigint NOT NULL CHECK(listing_revision>0),
 watch_id uuid NOT NULL, buyer_id uuid NOT NULL, seller_id uuid NOT NULL, seller_organization_id uuid,
 quote_id uuid NOT NULL UNIQUE REFERENCES l07_quotes(id), snapshot jsonb NOT NULL,
 state text NOT NULL DEFAULT 'open' CHECK(state IN ('open','acceptance_pending','accepted','rejected','expired','closed','lost')),
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>0), expires_at timestamptz NOT NULL,
 accepted_by uuid, acceptance_operation_id uuid REFERENCES l14_pricing_operations(id),
 orders_command jsonb, orders_result jsonb, created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX l14_offer_buyer ON l14_offers(buyer_id,created_at DESC);
CREATE INDEX l14_offer_seller ON l14_offers(seller_id,seller_organization_id,created_at DESC);
CREATE INDEX l14_offer_listing ON l14_offers(listing_id,state);
CREATE TABLE l14_offer_blocks (
 seller_scope text NOT NULL, buyer_id uuid NOT NULL, blocker_scope text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(seller_scope,buyer_id,blocker_scope)
);
