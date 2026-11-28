ALTER TABLE identity_possession_retention
 ADD COLUMN assignment_revision bigint CHECK(assignment_revision>0);
