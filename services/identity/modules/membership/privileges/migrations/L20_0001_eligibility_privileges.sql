CREATE TABLE identity_eligibility_privileges (
 operation_id uuid PRIMARY KEY, actor_id uuid NOT NULL REFERENCES identity_accounts(id),
 subject_id uuid NOT NULL REFERENCES identity_accounts(id), business_id uuid,
 permission text NOT NULL, reason text NOT NULL CHECK(length(reason) BETWEEN 10 AND 500),
 revoked boolean NOT NULL, fingerprint text NOT NULL, grant_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), CHECK(actor_id<>subject_id)
);
