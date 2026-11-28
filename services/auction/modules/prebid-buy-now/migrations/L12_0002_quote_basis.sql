-- Older pending intents remain held if they lack a provable admission revision.
ALTER TABLE auction_prebid_operations ADD COLUMN admission_revision bigint CHECK(admission_revision>0);
