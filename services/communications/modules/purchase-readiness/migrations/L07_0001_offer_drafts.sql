CREATE TABLE l07_offer_drafts (
 id uuid PRIMARY KEY, owner_id uuid NOT NULL, subject_id uuid NOT NULL, subject_revision integer NOT NULL CHECK(subject_revision>0),
 currency text NOT NULL CHECK(currency IN ('USD','LBP')), amount_minor bigint NOT NULL CHECK(amount_minor>0 AND amount_minor<=9000000000000),
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX l07_offer_drafts_owner ON l07_offer_drafts(owner_id,updated_at DESC,id DESC);
CREATE TABLE l07_offer_operations (owner_id uuid NOT NULL, idempotency_key text NOT NULL, request_hash text NOT NULL, result jsonb NOT NULL, PRIMARY KEY(owner_id,idempotency_key));
