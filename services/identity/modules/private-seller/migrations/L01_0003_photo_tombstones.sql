CREATE TABLE identity_possession_tombstones (
 photo_id uuid PRIMARY KEY, listing_id uuid NOT NULL, subject_id uuid NOT NULL,
 challenge_id uuid NOT NULL, removed_at timestamptz NOT NULL,
 final_review_at timestamptz NOT NULL, reviewer_id text NOT NULL,
 assignment_revision bigint NOT NULL CHECK(assignment_revision>0)
);
