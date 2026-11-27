CREATE TABLE l22_payment_notice_recovery (
 event_id uuid PRIMARY KEY REFERENCES l22_payment_notices(event_id),
 operator_id uuid NOT NULL,
 held_since timestamptz NOT NULL,
 response_due_at timestamptz NOT NULL,
 escalation_due_at timestamptz NOT NULL,
 next_action_en text NOT NULL DEFAULT 'Review verified contact and the retained Orders receipt; retry the same receipt.',
 next_action_ar text NOT NULL DEFAULT 'راجع جهة الاتصال المثبتة وإيصال الطلبات المحفوظ؛ أعد محاولة الإيصال نفسه.',
 escalated_at timestamptz,
 resolved_at timestamptz,
 CHECK (response_due_at = held_since + interval '24 hours'),
 CHECK (escalation_due_at = held_since + interval '48 hours')
);
CREATE INDEX l22_payment_notice_recovery_due
 ON l22_payment_notice_recovery(escalation_due_at) WHERE resolved_at IS NULL;
