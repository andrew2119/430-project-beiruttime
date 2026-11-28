CREATE TABLE identity_l19_possession (
 listing_id uuid PRIMARY KEY,
 subject_id uuid NOT NULL REFERENCES identity_accounts(id),
 proof jsonb NOT NULL
);
CREATE TABLE identity_l19_possession_receipts (
 subject_id uuid NOT NULL REFERENCES identity_accounts(id),
 operation_id text NOT NULL,
 digest text NOT NULL,
 result jsonb NOT NULL,
 PRIMARY KEY(subject_id,operation_id)
);
CREATE TABLE identity_l19_possession_photos (
 id uuid PRIMARY KEY,
 listing_id uuid NOT NULL REFERENCES identity_l19_possession(listing_id),
 subject_id uuid NOT NULL REFERENCES identity_accounts(id),
 challenge_id uuid NOT NULL UNIQUE,
 content bytea NOT NULL,
 created_at timestamptz NOT NULL,
 final_review_at timestamptz,
 retained_for_case boolean NOT NULL DEFAULT false
);
