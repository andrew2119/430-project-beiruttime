-- Private receipts only; commitment and money remain in their canonical owners.
CREATE TABLE l13_cancellation_receipts (
    operation_id uuid PRIMARY KEY,
    actor_id uuid NOT NULL,
    organization_id uuid,
    subject_id uuid NOT NULL,
    watch_id uuid NOT NULL,
    source_revision bigint NOT NULL CHECK (source_revision > 0),
    quote_id uuid NOT NULL,
    quote_revision bigint NOT NULL CHECK (quote_revision > 0),
    policy_revision bigint NOT NULL CHECK (policy_revision > 0),
    command jsonb NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX l13_cancellation_subject ON l13_cancellation_receipts(subject_id, created_at, operation_id);
