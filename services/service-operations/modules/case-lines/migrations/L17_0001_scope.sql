CREATE TABLE service_case_scopes (
 case_id uuid PRIMARY KEY, request_id uuid NOT NULL, organization_id uuid NOT NULL,
 buyer_id uuid NOT NULL, revision integer NOT NULL CHECK(revision>0), body jsonb NOT NULL
);
CREATE TABLE service_case_scope_operations (
 operation_id uuid PRIMARY KEY, actor_id uuid NOT NULL, command jsonb NOT NULL, receipt jsonb NOT NULL
);
CREATE TABLE service_case_scope_outbox (
 operation_id uuid PRIMARY KEY REFERENCES service_case_scope_operations(operation_id),
 case_id uuid NOT NULL, revision integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
