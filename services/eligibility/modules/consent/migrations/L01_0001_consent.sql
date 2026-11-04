CREATE TABLE eligibility_consents (
 id uuid PRIMARY KEY, buyer_id uuid NOT NULL, brand_id uuid NOT NULL, request_id uuid NOT NULL,
 request_revision integer NOT NULL CHECK(request_revision>0), revision integer NOT NULL CHECK(revision>0),
 purpose text NOT NULL CHECK(purpose='brand-request-identity'), policy_version text NOT NULL CHECK(policy_version='demo-identity-v1'),
 status text NOT NULL CHECK(status IN ('active','refused','withdrawal_pending','withdrawn')),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(buyer_id,request_id,request_revision,purpose)
);
CREATE TABLE eligibility_consent_evidence (
 id uuid PRIMARY KEY, consent_id uuid NOT NULL REFERENCES eligibility_consents(id),
 content bytea NOT NULL CHECK(octet_length(content) BETWEEN 5 AND 65536), sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE eligibility_consent_assignments (
 consent_id uuid NOT NULL REFERENCES eligibility_consents(id), reviewer_id uuid NOT NULL,
 revoked_at timestamptz, PRIMARY KEY(consent_id,reviewer_id)
);
CREATE TABLE eligibility_consent_operations (
 buyer_id uuid NOT NULL, key text NOT NULL, digest text NOT NULL, result jsonb NOT NULL, PRIMARY KEY(buyer_id,key)
);
CREATE TABLE eligibility_consent_fences (
 consent_id uuid NOT NULL REFERENCES eligibility_consents(id), revision integer NOT NULL,
 source text NOT NULL CHECK(source IN ('catalog','orders')), acknowledged_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(consent_id,revision,source)
);
CREATE TABLE eligibility_consent_audit (
 id uuid PRIMARY KEY, actor_id uuid NOT NULL, consent_id uuid NOT NULL, action text NOT NULL,
 outcome text NOT NULL, request_id text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
