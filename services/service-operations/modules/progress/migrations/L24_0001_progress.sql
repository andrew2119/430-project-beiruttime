CREATE TABLE service_progress_jobs (
    subject_id uuid PRIMARY KEY,
    revision bigint NOT NULL CHECK (revision >= 0),
    reports jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE service_progress_operations (
    operation_id uuid PRIMARY KEY,
    actor_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    request_hash text NOT NULL,
    result jsonb NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE service_progress_history (
    subject_id uuid NOT NULL,
    revision bigint NOT NULL,
    actor_id uuid NOT NULL,
    operation_id uuid NOT NULL UNIQUE,
    report jsonb NOT NULL,
    PRIMARY KEY(subject_id, revision)
);
CREATE TABLE service_progress_outbox (
    operation_id uuid PRIMARY KEY,
    event_type text NOT NULL CHECK (event_type = 'service.progress.reported.v1'),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    delivered_at timestamptz
);
