CREATE TABLE l02_businesses (
 id uuid PRIMARY KEY, legal_name text NOT NULL CHECK(length(legal_name) BETWEEN 2 AND 180),
 public_name text NOT NULL CHECK(length(public_name) BETWEEN 2 AND 120),
 kind text NOT NULL CHECK(kind IN ('dealer','brand')),
 capabilities text[] NOT NULL, assurance_reference text NOT NULL,
 state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','revoked')),
 revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
 sample boolean NOT NULL DEFAULT false, created_by uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE l02_business_history (
 id bigserial PRIMARY KEY, business_id uuid NOT NULL REFERENCES l02_businesses(id),
 actor_id uuid NOT NULL, revision integer NOT NULL, action text NOT NULL,
 reason text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(business_id,revision)
);
CREATE TABLE l02_business_operations (
 actor_id uuid NOT NULL, operation_key text NOT NULL, fingerprint text NOT NULL,
 result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(actor_id,operation_key)
);
