CREATE TABLE moderation_cases (
 id uuid PRIMARY KEY, reporter_id uuid NOT NULL, target_kind text NOT NULL CHECK(target_kind IN ('listing','user','message')),
 target_id uuid NOT NULL, subject_id uuid NOT NULL, category text NOT NULL,
 evidence text NOT NULL CHECK(length(evidence) BETWEEN 1 AND 4000),
 assigned_to uuid, status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','assigned','decided','appealed')),
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0), last_action text, last_event_id uuid,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK(assigned_to IS NULL OR (assigned_to<>subject_id AND assigned_to<>reporter_id))
);
CREATE INDEX moderation_queue ON moderation_cases(status,created_at,id);
CREATE INDEX moderation_reporter ON moderation_cases(reporter_id,created_at);
CREATE TABLE moderation_audit (
 id uuid PRIMARY KEY, case_id uuid NOT NULL REFERENCES moderation_cases(id), actor_id uuid NOT NULL,
 kind text NOT NULL, reason text NOT NULL CHECK(length(reason) BETWEEN 1 AND 4000),
 revision integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(case_id,revision)
);
CREATE TABLE moderation_operations (
 actor_id uuid NOT NULL, key text NOT NULL, request_hash text NOT NULL, result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(actor_id,key)
);
