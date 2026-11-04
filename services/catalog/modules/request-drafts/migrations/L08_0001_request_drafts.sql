CREATE TABLE l08_request_drafts (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
    content jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX l08_drafts_owner ON l08_request_drafts(owner_id,updated_at DESC,id);
CREATE TABLE l08_draft_operations (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    operation_key text NOT NULL CHECK(length(operation_key) BETWEEN 1 AND 100),
    digest text NOT NULL CHECK(length(digest)=64),
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(owner_id,operation_key)
);
CREATE TABLE l08_draft_audit (
    id bigserial PRIMARY KEY,
    draft_id uuid NOT NULL REFERENCES l08_request_drafts(id),
    actor_id uuid NOT NULL,
    action text NOT NULL,
    revision bigint NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
