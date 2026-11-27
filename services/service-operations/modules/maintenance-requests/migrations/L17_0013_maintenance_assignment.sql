CREATE SEQUENCE maintenance_assessment_assignment_epochs AS bigint START WITH 2;
CREATE TABLE maintenance_assessment_assignments (
    request_id uuid PRIMARY KEY REFERENCES maintenance_requests(id),
    organization_id uuid NOT NULL,
    assessor_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    request_revision integer NOT NULL CHECK (request_revision > 0),
    queue_epoch bigint NOT NULL DEFAULT nextval('maintenance_assessment_assignment_epochs'),
    changed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX maintenance_assessment_assignee ON maintenance_assessment_assignments(organization_id, assessor_id, request_id);
CREATE TABLE maintenance_assessment_decisions (
    request_id uuid PRIMARY KEY REFERENCES maintenance_requests(id),
    actor_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    watch_id uuid NOT NULL,
    assignment_revision integer NOT NULL CHECK (assignment_revision > 0),
    request_revision integer NOT NULL CHECK (request_revision > 0),
    custody_receipt_id uuid NOT NULL,
    custody_receipt_revision integer NOT NULL CHECK (custody_receipt_revision > 0),
    order_id uuid NOT NULL,
    watch_revision bigint NOT NULL CHECK (watch_revision > 0),
    incident_revision bigint NOT NULL CHECK (incident_revision >= 0),
    state text NOT NULL CHECK (state IN ('confirmed', 'rejected')),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE maintenance_staff_operations (
    operation_id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES maintenance_requests(id),
    actor_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    kind text NOT NULL CHECK(kind IN ('assignment','confirmation')),
    command jsonb NOT NULL,
    receipt jsonb NOT NULL
);
