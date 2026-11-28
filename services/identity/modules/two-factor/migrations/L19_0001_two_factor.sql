CREATE TABLE identity_l19_factors (
    subject_id text PRIMARY KEY,
    data bytea NOT NULL
);
CREATE TABLE identity_l19_factor_operations (
    subject_id text NOT NULL REFERENCES identity_l19_factors(subject_id),
    operation_id text NOT NULL,
    digest text NOT NULL,
    result bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(subject_id, operation_id)
);
CREATE TABLE identity_l19_factor_limits (
    subject_id text PRIMARY KEY,
    window_at bigint NOT NULL,
    attempts integer NOT NULL CHECK(attempts > 0)
);
CREATE TABLE identity_l19_factor_outbox (
    operation_id text NOT NULL,
    subject_id text NOT NULL,
    kind text NOT NULL CHECK(kind = 'revoke_sessions'),
    acknowledged boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(subject_id, operation_id),
    FOREIGN KEY(subject_id, operation_id)
        REFERENCES identity_l19_factor_operations(subject_id, operation_id)
);
