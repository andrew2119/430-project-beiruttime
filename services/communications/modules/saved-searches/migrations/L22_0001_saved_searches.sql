CREATE TABLE l22_saved_searches (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    criteria jsonb NOT NULL,
    semantics_revision text NOT NULL,
    alerts_enabled boolean NOT NULL,
    state text NOT NULL CHECK (state IN ('saved','removed')),
    revision bigint NOT NULL CHECK (revision > 0),
    created_at timestamptz NOT NULL,
    eligible_at timestamptz NOT NULL
);
CREATE INDEX l22_search_owner ON l22_saved_searches(owner_id, created_at, id);
CREATE TABLE l22_search_operations (
    owner_id uuid NOT NULL,
    operation_id uuid NOT NULL,
    request_hash text NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY (owner_id, operation_id)
);
CREATE TABLE l22_match_deliveries (
    owner_id uuid NOT NULL,
    occurrence_id uuid NOT NULL,
    request_hash text NOT NULL,
    PRIMARY KEY (owner_id, occurrence_id)
);
CREATE TABLE l22_match_notices (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    subscription_id uuid NOT NULL REFERENCES l22_saved_searches(id),
    occurrence_id uuid NOT NULL,
    listing_id uuid NOT NULL,
    watch_id uuid NOT NULL,
    source_revision bigint NOT NULL CHECK (source_revision > 0),
    event_time timestamptz NOT NULL,
    sample boolean NOT NULL,
    read boolean NOT NULL DEFAULT false,
    cleared boolean NOT NULL DEFAULT false,
    revision bigint NOT NULL DEFAULT 1,
    UNIQUE(subscription_id, occurrence_id)
);
CREATE INDEX l22_notice_owner ON l22_match_notices(owner_id, event_time, id);
