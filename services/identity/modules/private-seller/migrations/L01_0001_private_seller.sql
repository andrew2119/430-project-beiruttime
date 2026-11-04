CREATE TABLE identity_private_applications (
 id uuid PRIMARY KEY, subject_id uuid NOT NULL UNIQUE REFERENCES identity_accounts(id),
 revision integer NOT NULL CHECK(revision>0), status text NOT NULL CHECK(status IN ('pending','correction','approved','rejected','suspended')),
 identity_name text NOT NULL, contact text NOT NULL, payout_reference text NOT NULL CHECK(payout_reference LIKE 'DEMO-%'),
 reason text NOT NULL DEFAULT '', created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE identity_private_evidence (
 id uuid PRIMARY KEY, application_id uuid NOT NULL REFERENCES identity_private_applications(id),
 subject_id uuid NOT NULL REFERENCES identity_accounts(id), kind text NOT NULL CHECK(kind IN ('identity','possession')),
 content bytea NOT NULL CHECK(octet_length(content) BETWEEN 5 AND 65536), sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX identity_private_evidence_case ON identity_private_evidence(application_id);
CREATE TABLE identity_private_assignments (
 application_id uuid NOT NULL REFERENCES identity_private_applications(id), reviewer_id uuid NOT NULL REFERENCES identity_accounts(id),
 revoked_at timestamptz, PRIMARY KEY(application_id,reviewer_id)
);
CREATE TABLE identity_private_operations (
 subject_id uuid NOT NULL, key text NOT NULL, digest text NOT NULL, result jsonb NOT NULL,
 PRIMARY KEY(subject_id,key)
);
