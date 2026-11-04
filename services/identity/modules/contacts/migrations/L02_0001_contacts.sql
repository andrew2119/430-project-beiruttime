CREATE TABLE l02_contacts (
 subject_id uuid PRIMARY KEY, email text, phone text,
 email_verified_at timestamptz, phone_verified_at timestamptz,
 revision integer NOT NULL DEFAULT 1, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE l02_contact_challenges (
 id uuid PRIMARY KEY, subject_id uuid NOT NULL, channel text NOT NULL CHECK(channel IN ('email','phone')),
 recipient text NOT NULL, code_digest text NOT NULL, expires_at timestamptz NOT NULL,
 attempts integer NOT NULL DEFAULT 0, consumed_at timestamptz, simulated_code text,
 created_at timestamptz NOT NULL DEFAULT now(), contact_revision integer NOT NULL
);
CREATE INDEX l02_contact_recent ON l02_contact_challenges(subject_id,created_at);
CREATE TABLE l02_contact_operations (
 subject_id uuid NOT NULL, operation_key text NOT NULL, fingerprint text NOT NULL, result jsonb NOT NULL,
 PRIMARY KEY(subject_id,operation_key)
);
