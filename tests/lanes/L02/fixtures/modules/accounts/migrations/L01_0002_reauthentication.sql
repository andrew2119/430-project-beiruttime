CREATE TABLE identity_reauth_proofs (
 hash text PRIMARY KEY CHECK(length(hash)=64), subject_id uuid NOT NULL REFERENCES identity_accounts(id),
 session_id uuid NOT NULL REFERENCES identity_sessions(id), purpose text NOT NULL CHECK(purpose='contact-change'),
 binding_hash text NOT NULL CHECK(length(binding_hash)=64), expires_at timestamptz NOT NULL,
 consumed_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX identity_reauth_subject ON identity_reauth_proofs(subject_id,session_id);
