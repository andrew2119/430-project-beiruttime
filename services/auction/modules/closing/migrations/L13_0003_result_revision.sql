ALTER TABLE l13_auction_closes
 ADD COLUMN result_revision bigint NOT NULL DEFAULT 1 CHECK(result_revision>0);
