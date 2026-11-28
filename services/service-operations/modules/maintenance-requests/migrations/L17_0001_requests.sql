CREATE TABLE maintenance_requests (
 id uuid PRIMARY KEY, operation_id uuid NOT NULL UNIQUE, actor_id uuid NOT NULL,
 organization_id uuid NOT NULL, watch_id uuid NOT NULL, private_request jsonb NOT NULL,
 revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
 state text NOT NULL DEFAULT 'submitted' CHECK(state = 'submitted'),
 submitted_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE maintenance_request_operations (
 operation_id uuid PRIMARY KEY, actor_id uuid NOT NULL, organization_id uuid NOT NULL,
 request_hash text NOT NULL, result jsonb NOT NULL
);
CREATE TABLE maintenance_request_outbox (
 event_id uuid PRIMARY KEY, request_id uuid NOT NULL REFERENCES maintenance_requests(id),
 event_type text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 delivered_at timestamptz, attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 8)
);
