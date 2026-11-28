CREATE TABLE reduction_records (
 id uuid PRIMARY KEY, organization_id uuid NOT NULL, subject_id uuid NOT NULL,
 watch_id uuid NOT NULL, revision integer NOT NULL CHECK(revision > 0),
 state text NOT NULL CHECK(state IN ('requested','unresolved','recorded')),
 request jsonb NOT NULL, result jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE reduction_operations (
 operation_id uuid PRIMARY KEY, record_id uuid NOT NULL REFERENCES reduction_records(id),
 actor_id uuid NOT NULL, organization_id uuid NOT NULL,
 request_hash text NOT NULL, result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reduction_record_scope ON reduction_records(organization_id,subject_id,id);
