CREATE TABLE l20_private_review_cases (
    case_id uuid PRIMARY KEY,
    snapshot jsonb NOT NULL
);
CREATE TABLE l20_private_review_receipts (
    case_id uuid NOT NULL REFERENCES l20_private_review_cases(case_id),
    operation_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    digest text NOT NULL,
    result jsonb NOT NULL,
    PRIMARY KEY (case_id, operation_id)
);
CREATE TABLE l20_private_review_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id uuid NOT NULL,
    actor_id uuid NOT NULL,
    action text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
