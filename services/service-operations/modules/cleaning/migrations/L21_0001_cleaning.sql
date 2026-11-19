CREATE TABLE l21_cleaning_requests (
    subject_id uuid PRIMARY KEY,
    result jsonb NOT NULL
);
CREATE TABLE l21_cleaning_receipts (
    operation_id uuid PRIMARY KEY,
    actor_id uuid NOT NULL,
    subject_id uuid NOT NULL REFERENCES l21_cleaning_requests(subject_id),
    request_hash text NOT NULL CHECK(length(request_hash)=64),
    result jsonb NOT NULL
);
