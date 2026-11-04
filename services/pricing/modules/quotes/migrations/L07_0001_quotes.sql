CREATE TABLE l07_quotes (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL, idempotency_key text NOT NULL,
 request_hash text NOT NULL, snapshot jsonb NOT NULL,
 created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 reviewed_at timestamptz, revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
 UNIQUE(owner_id,idempotency_key), CHECK(expires_at > created_at)
);
CREATE INDEX l07_quotes_owner ON l07_quotes(owner_id,created_at DESC,id DESC);
CREATE TABLE l07_quote_reviews (
 quote_id uuid PRIMARY KEY REFERENCES l07_quotes(id), owner_id uuid NOT NULL,
 idempotency_key text NOT NULL, request_hash text NOT NULL, reviewed_at timestamptz NOT NULL,
 UNIQUE(owner_id,idempotency_key)
);
