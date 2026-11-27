ALTER TABLE l14_quote_decisions ADD COLUMN repair_recovery jsonb;
ALTER TABLE l14_quote_decisions ADD CONSTRAINT l14_repair_recovery_object
    CHECK (repair_recovery IS NULL OR jsonb_typeof(repair_recovery) = 'object');
CREATE INDEX l14_repair_recovery_due ON l14_quote_decisions
    ((repair_recovery->>'next_review_at')) WHERE repair_recovery IS NOT NULL;
