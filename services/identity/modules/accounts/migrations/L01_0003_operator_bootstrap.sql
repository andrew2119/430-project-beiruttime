-- Permanent, audited one-time seal; revoking an operator must not reopen bootstrap.
CREATE TABLE identity_operator_bootstrap (
 singleton smallint PRIMARY KEY CHECK(singleton=1),
 subject_id uuid NOT NULL REFERENCES identity_accounts(id),
 reason text NOT NULL CHECK(length(reason) BETWEEN 10 AND 500),
 request_id text NOT NULL UNIQUE,
 created_at timestamptz NOT NULL DEFAULT now()
);
