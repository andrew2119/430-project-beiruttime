CREATE TABLE l02_listing_reviews (
    listing_id uuid PRIMARY KEY,
    binding jsonb NOT NULL,
    proof jsonb,
    photo bytea,
    stock_clearance jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE l02_listing_stock (
    identity_digest text NOT NULL,
    watch_id uuid NOT NULL,
    listing_id uuid NOT NULL,
    PRIMARY KEY(identity_digest, watch_id, listing_id)
);
CREATE TABLE l02_listing_review_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    listing_id uuid NOT NULL,
    actor_id uuid,
    action text NOT NULL,
    revision integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE l02_listing_review_receipts (
    actor_id uuid NOT NULL,
    operation_id text NOT NULL,
    fingerprint text NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY(actor_id, operation_id)
);
