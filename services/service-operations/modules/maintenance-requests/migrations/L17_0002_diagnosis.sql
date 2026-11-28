CREATE TABLE maintenance_photos (
 id uuid PRIMARY KEY, operation_id uuid NOT NULL UNIQUE, actor_id uuid NOT NULL, watch_id uuid NOT NULL,
 organization_id uuid NOT NULL, request_operation_id uuid NOT NULL, content bytea NOT NULL CHECK(octet_length(content)<=262144)
);
CREATE TABLE service_diagnoses (
 case_id uuid PRIMARY KEY, request_id uuid NOT NULL REFERENCES maintenance_requests(id),
 organization_id uuid NOT NULL, watch_id uuid NOT NULL, revision integer NOT NULL CHECK(revision>0),
 assessment_id uuid NOT NULL UNIQUE, body jsonb NOT NULL
);
CREATE TABLE service_diagnosis_operations (
 operation_id uuid PRIMARY KEY, actor_id uuid NOT NULL, organization_id uuid NOT NULL,
 command jsonb NOT NULL, receipt jsonb NOT NULL
);
CREATE TABLE service_diagnosis_outbox (
 operation_id uuid PRIMARY KEY REFERENCES service_diagnosis_operations(operation_id),
 case_id uuid NOT NULL, revision integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
