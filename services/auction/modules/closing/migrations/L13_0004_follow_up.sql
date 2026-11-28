ALTER TABLE l13_auction_closes
 ADD COLUMN responsible_operator_id uuid,
 ADD COLUMN next_action text CHECK(next_action IN ('reconcile_allocation','review_allocation_denial','reconcile_legacy_purchase')),
 ADD COLUMN response_due_at timestamptz,
 ADD COLUMN escalation_due_at timestamptz,
 ADD COLUMN escalated_at timestamptz;
-- Existing unresolved records retain their age until a scoped assignment is supplied.
UPDATE l13_auction_closes SET
 next_action=CASE state WHEN 'ended_legacy_review' THEN 'reconcile_legacy_purchase'
 WHEN 'allocation_denied' THEN 'review_allocation_denial' ELSE 'reconcile_allocation' END,
 response_due_at=created_at+interval '24 hours',
 escalation_due_at=created_at+interval '48 hours'
 WHERE state IN ('allocation_pending','allocation_denied','ended_legacy_review');
