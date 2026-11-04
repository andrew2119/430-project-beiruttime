CREATE TABLE l08_watches (
    id uuid PRIMARY KEY,
    listing_id uuid NOT NULL UNIQUE,
    seller_id uuid NOT NULL,
    organization_id uuid,
    listing_revision bigint NOT NULL CHECK(listing_revision>0),
    sale_mode text NOT NULL CHECK(sale_mode IN ('fixed','auction','seller_base')),
    status text NOT NULL DEFAULT 'available' CHECK(status IN ('available','reserved','fenced')),
    source_id uuid,
    revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE l08_orders (
    id uuid PRIMARY KEY,
    watch_id uuid NOT NULL REFERENCES l08_watches(id),
    buyer_id uuid NOT NULL,
    seller_id uuid NOT NULL,
    organization_id uuid,
    quote_id uuid NOT NULL UNIQUE,
    state text NOT NULL CHECK(state IN ('awaiting_payment','payment_unknown','expired_fenced')),
    currency text NOT NULL CHECK(currency IN ('USD','LBP')),
    total_minor bigint NOT NULL CHECK(total_minor BETWEEN 0 AND 9000000000000000),
    revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
    deadline timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK(buyer_id<>seller_id)
);
-- All Sprint 1 order states retain the physical commitment, including expiry.
CREATE UNIQUE INDEX l08_one_commitment ON l08_orders(watch_id);
CREATE INDEX l08_orders_buyer ON l08_orders(buyer_id,created_at DESC,id);
CREATE INDEX l08_orders_seller ON l08_orders(seller_id,created_at DESC,id);
CREATE INDEX l08_orders_expiry ON l08_orders(deadline) WHERE state='awaiting_payment';
CREATE TABLE l08_operations (
    id uuid PRIMARY KEY,
    actor_key text NOT NULL,
    idempotency_key text NOT NULL CHECK(length(idempotency_key) BETWEEN 1 AND 100),
    digest text NOT NULL CHECK(length(digest)=64),
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(actor_key,idempotency_key)
);
CREATE TABLE l08_audit (
    id bigserial PRIMARY KEY,
    resource_id uuid NOT NULL,
    actor_key text NOT NULL,
    action text NOT NULL,
    reason text NOT NULL CHECK(length(reason) BETWEEN 1 AND 200),
    revision bigint NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX l08_audit_resource ON l08_audit(resource_id,id);
CREATE TABLE l08_intake (
    id uuid PRIMARY KEY,
    order_id uuid NOT NULL REFERENCES l08_orders(id),
    actor_id uuid NOT NULL,
    actual_watch text NOT NULL CHECK(length(actual_watch) BETWEEN 1 AND 300),
    accessories jsonb NOT NULL,
    location text NOT NULL CHECK(length(location) BETWEEN 1 AND 200),
    condition text NOT NULL CHECK(length(condition) BETWEEN 1 AND 2000),
    occurred_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    revision bigint NOT NULL
);
