-- CP B-27: local invariants; Identity remains the authority for official onboarding.
CREATE TABLE directory_profiles (
 organization_id uuid PRIMARY KEY,
 revision integer NOT NULL CHECK (revision > 0),
 capabilities text[] NOT NULL CHECK (cardinality(capabilities) BETWEEN 1 AND 8),
 contact text NOT NULL CHECK (length(contact) BETWEEN 1 AND 160),
 visit_en text NOT NULL CHECK (length(visit_en) BETWEEN 1 AND 400),
 visit_ar text NOT NULL CHECK (length(visit_ar) BETWEEN 1 AND 400),
 scope_en text NOT NULL CHECK (length(scope_en) BETWEEN 1 AND 600),
 scope_ar text NOT NULL CHECK (length(scope_ar) BETWEEN 1 AND 600),
 published boolean NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE directory_choices (
 actor_id uuid PRIMARY KEY,
 id uuid NOT NULL UNIQUE,
 organization_id uuid NOT NULL REFERENCES directory_profiles(organization_id),
 capability text NOT NULL,
 purpose text NOT NULL CHECK (purpose IN ('servicing','customization')),
 revision integer NOT NULL CHECK (revision > 0),
 profile_revision integer NOT NULL CHECK (profile_revision > 0),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE directory_commands (
 actor_id uuid NOT NULL,
 command text NOT NULL,
 key text NOT NULL CHECK (length(key) BETWEEN 8 AND 100),
 digest text NOT NULL CHECK (length(digest)=64),
 result jsonb NOT NULL,
 PRIMARY KEY(actor_id,command,key)
);
