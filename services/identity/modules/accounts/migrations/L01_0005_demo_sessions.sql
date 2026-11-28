-- Activations of switch-gated sample-account entry: one per key fingerprint, end time and
-- Operator setting, each entered the first time any Identity process puts its values on record.
-- A closed activation never opens again, so its link sessions end for good.
CREATE TABLE identity_demo_activations (
 activation text PRIMARY KEY CHECK(activation ~ '^[0-9a-f]{64}$'),
 until_at timestamptz NOT NULL,
 opened_at timestamptz NOT NULL DEFAULT now(),
 closed_at timestamptz NULL
);
-- Sessions issued by sample-account entry, each bound to the activation that issued it.
CREATE TABLE identity_demo_sessions (
 session_id uuid PRIMARY KEY REFERENCES identity_sessions(id),
 role text NOT NULL CHECK(role IN ('buyer','seller','staff','operator','rival')),
 activation text NOT NULL REFERENCES identity_demo_activations(activation),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX identity_demo_sessions_activation ON identity_demo_sessions(activation);
-- Each Identity process takes one number from this sequence when it starts (its first sweep or
-- request), so the database, not any process clock, orders process starts.
CREATE SEQUENCE identity_demo_starts AS bigint;
-- The one activation entry may use now (NULL while entry is off), and the highest start number of
-- the processes that put it on record, in one row. Values never on record before, from a process
-- numbered no lower, can take it, and a process with entry off takes it whatever its number; either
-- closes every other open activation, so every replica follows the latest deploy (see
-- modules/accounts/demo_entry.py).
CREATE TABLE identity_demo_fence (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 start_number bigint NULL,
 activation text NULL CHECK(activation ~ '^[0-9a-f]{64}$')
);
INSERT INTO identity_demo_fence(singleton) VALUES(true);
