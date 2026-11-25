ALTER TABLE identity_possession_retention
 ADD COLUMN final_review_at timestamptz,
 ADD COLUMN active_case boolean;
