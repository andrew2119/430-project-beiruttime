CREATE TABLE l02_review_evidence_audit (
 id bigserial PRIMARY KEY, actor_id uuid NOT NULL, review_id uuid NOT NULL,
 evidence_id uuid, outcome text NOT NULL CHECK(outcome IN ('allowed','denied','unavailable')),
 request_id text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX l02_review_evidence_audit_resource ON l02_review_evidence_audit(review_id,created_at);
