ALTER TABLE l02_membership_history ADD COLUMN snapshot jsonb NOT NULL DEFAULT '{}'::jsonb;
