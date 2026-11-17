CREATE TABLE eligibility_decision_states (
 consent_id uuid PRIMARY KEY REFERENCES eligibility_consents(id),
 revision integer NOT NULL DEFAULT 0 CHECK (revision >= 0),
 state jsonb NOT NULL DEFAULT '{"revision":0,"reviews":[],"grants":[]}'::jsonb
);
CREATE TABLE eligibility_decision_operations (
 operation_id uuid PRIMARY KEY,
 actor_id uuid NOT NULL,
 consent_id uuid NOT NULL REFERENCES eligibility_consents(id),
 digest text NOT NULL,
 permission text NOT NULL,
 result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
