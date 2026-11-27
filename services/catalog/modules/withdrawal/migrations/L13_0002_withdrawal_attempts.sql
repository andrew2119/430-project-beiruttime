ALTER TABLE l13_listing_withdrawals
 DROP CONSTRAINT l13_listing_withdrawals_listing_id_key;
CREATE UNIQUE INDEX l13_one_pending_withdrawal
 ON l13_listing_withdrawals(listing_id) WHERE state='pending';
