CREATE TABLE l02_memberships (
 id uuid PRIMARY KEY, business_id uuid NOT NULL, subject_id uuid NOT NULL,
 capabilities text[] NOT NULL, qualifications text[] NOT NULL DEFAULT '{}', intervention_scope text NOT NULL,
 state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','suspended','revoked')),
 revision integer NOT NULL DEFAULT 1, changed_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(business_id,subject_id)
);
CREATE INDEX l02_membership_subject ON l02_memberships(subject_id,state);
CREATE TABLE l02_membership_history (
 id bigserial PRIMARY KEY, membership_id uuid NOT NULL REFERENCES l02_memberships(id),
 actor_id uuid NOT NULL, revision integer NOT NULL, reason text NOT NULL,
 state text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(membership_id,revision)
);
CREATE TABLE l02_membership_operations (
 actor_id uuid NOT NULL, operation_key text NOT NULL, fingerprint text NOT NULL, result jsonb NOT NULL,
 PRIMARY KEY(actor_id,operation_key)
);
