ALTER TABLE l07_notices DROP CONSTRAINT l07_notices_kind_check;
ALTER TABLE l07_notices ADD CONSTRAINT l07_notices_kind_check CHECK(kind IN ('quote_ready','outbid','reservation_ready','payment_required','case_update'));
