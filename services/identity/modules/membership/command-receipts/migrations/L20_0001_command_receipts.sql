CREATE TABLE l20_business_command_receipts (
 actor_id uuid NOT NULL,
 operation_id uuid NOT NULL,
 subject_id uuid NOT NULL,
 business_id uuid,
 watch_id uuid,
 expected_revision integer NOT NULL CHECK (expected_revision >= 0),
 fingerprint text NOT NULL CHECK (length(fingerprint) = 64),
 result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (actor_id, operation_id)
);
