CREATE TABLE l02_private_reviews (
 id uuid PRIMARY KEY, application_id uuid NOT NULL UNIQUE, applicant_id uuid NOT NULL,
 reviewer_id uuid NOT NULL, application_revision integer NOT NULL,
 state text NOT NULL DEFAULT 'assigned' CHECK(state IN ('assigned','correction','approved','rejected','suspended')),
 revision integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(reviewer_id<>applicant_id)
);
CREATE TABLE l02_private_review_history (
 id bigserial PRIMARY KEY, review_id uuid NOT NULL REFERENCES l02_private_reviews(id), actor_id uuid NOT NULL,
 revision integer NOT NULL, state text NOT NULL, reason text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(review_id,revision)
);
CREATE TABLE l02_private_review_operations (
 actor_id uuid NOT NULL, operation_key text NOT NULL, fingerprint text NOT NULL, result jsonb NOT NULL,
 PRIMARY KEY(actor_id,operation_key)
);
