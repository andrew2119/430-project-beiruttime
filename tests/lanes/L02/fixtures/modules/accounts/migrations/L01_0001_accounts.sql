CREATE TABLE identity_accounts (
 id uuid PRIMARY KEY, email text NOT NULL UNIQUE CHECK(length(email)<=254),
 display_name text NOT NULL CHECK(length(display_name) BETWEEN 1 AND 100),
 password_hash text NOT NULL, status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended')),
 access_revision integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE identity_sessions (
 id uuid PRIMARY KEY, subject_id uuid NOT NULL REFERENCES identity_accounts(id),
 expires_at timestamptz NOT NULL, revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX identity_sessions_subject ON identity_sessions(subject_id);
CREATE TABLE identity_refresh_tokens (
 hash text PRIMARY KEY CHECK(length(hash)=64), session_id uuid NOT NULL REFERENCES identity_sessions(id), consumed_at timestamptz
);
CREATE TABLE identity_password_resets (
 hash text PRIMARY KEY CHECK(length(hash)=64), subject_id uuid NOT NULL REFERENCES identity_accounts(id),
 expires_at timestamptz NOT NULL, consumed_at timestamptz
);
-- Same-domain extension seam: L02 grants exact roles/permissions after its authorized operations.
CREATE TABLE identity_access_grants (
 id uuid PRIMARY KEY, subject_id uuid NOT NULL REFERENCES identity_accounts(id),
 organization_id uuid, role text NOT NULL, permissions text[] NOT NULL DEFAULT '{}',
 revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX identity_grants_subject ON identity_access_grants(subject_id) WHERE revoked_at IS NULL;
CREATE TABLE identity_auth_limits (
 scope text PRIMARY KEY, attempts integer NOT NULL, resets_at timestamptz NOT NULL
);
CREATE TABLE identity_demo_mail (
 id uuid PRIMARY KEY, subject_id uuid NOT NULL REFERENCES identity_accounts(id),
 ciphertext text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE identity_account_operations (
 key text PRIMARY KEY, digest text NOT NULL, subject_id uuid NOT NULL REFERENCES identity_accounts(id)
);
CREATE TABLE identity_security_audit (
 id uuid PRIMARY KEY, actor_id uuid, resource_id uuid, action text NOT NULL, outcome text NOT NULL,
 request_id text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now()
);
