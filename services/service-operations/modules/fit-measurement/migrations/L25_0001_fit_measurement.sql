CREATE TABLE l25_fit_records (
    subject_id uuid NOT NULL,
    watch_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    result jsonb NOT NULL,
    PRIMARY KEY(subject_id, watch_id, organization_id)
);
CREATE TABLE l25_fit_operations (
    operation_id uuid PRIMARY KEY,
    actor_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    request_hash text NOT NULL,
    result jsonb NOT NULL
);
CREATE TABLE l25_fit_outbox (
    operation_id uuid PRIMARY KEY REFERENCES l25_fit_operations(operation_id),
    schema_version text NOT NULL DEFAULT 'service-operations.fit-recorded.v1',
    subject_id uuid NOT NULL,
    watch_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    revision integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    delivered_at timestamptz
);
