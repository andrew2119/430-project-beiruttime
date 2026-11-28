CREATE TABLE l20_history_operations (
    operation_id uuid PRIMARY KEY,
    actor_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    watch_id uuid NOT NULL,
    organization_id uuid,
    expected_revision bigint NOT NULL CHECK (expected_revision >= 0),
    page integer NOT NULL CHECK (page >= 0 AND page <= 10000),
    page_size integer NOT NULL CHECK (page_size BETWEEN 1 AND 50)
);

CREATE TABLE l20_history_publications (
    watch_id uuid PRIMARY KEY,
    revision bigint NOT NULL CHECK (revision >= 0),
    safe_entries jsonb NOT NULL CHECK (jsonb_typeof(safe_entries) = 'array')
);

CREATE TABLE l20_history_publication_receipts (
    operation_id uuid PRIMARY KEY,
    actor_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    organization_id uuid,
    watch_id uuid NOT NULL,
    expected_revision bigint NOT NULL,
    selected_job_ids jsonb NOT NULL,
    result jsonb NOT NULL
);
