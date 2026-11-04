ALTER TABLE l07_notices DROP CONSTRAINT l07_notices_kind_check;
ALTER TABLE l07_notices ADD CONSTRAINT l07_notices_kind_check CHECK(kind IN ('quote_ready','bid_accepted','outbid','reservation_ready','payment_required','case_update'));
-- Legacy bridge events carry a sequence, not an auction revision. Unknown is explicit.
ALTER TABLE l07_notices ALTER COLUMN resource_revision DROP NOT NULL;
