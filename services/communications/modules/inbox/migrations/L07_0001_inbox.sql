CREATE TABLE l07_notices (
 id uuid PRIMARY KEY, recipient_id uuid NOT NULL, source text NOT NULL, occurrence_id text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('quote_ready','outbid','reservation_ready','case_update')),
 resource_id uuid NOT NULL, resource_owner_id uuid NOT NULL, resource_revision integer NOT NULL CHECK(resource_revision > 0),
 event_time timestamptz NOT NULL, received_at timestamptz NOT NULL DEFAULT now(), required boolean NOT NULL, sample boolean NOT NULL,
 read_at timestamptz, cleared_at timestamptz, revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
 UNIQUE(recipient_id,source,occurrence_id)
);
CREATE INDEX l07_notice_owner ON l07_notices(recipient_id,event_time DESC,id DESC) WHERE cleared_at IS NULL;
CREATE TABLE l07_notice_preferences (owner_id uuid PRIMARY KEY, optional_enabled boolean NOT NULL, revision integer NOT NULL CHECK(revision > 0));
CREATE TABLE l07_notice_operations (owner_id uuid NOT NULL, idempotency_key text NOT NULL, request_hash text NOT NULL, result jsonb NOT NULL, PRIMARY KEY(owner_id,idempotency_key));
