CREATE TABLE maintenance_predecision_leases (
    request_id uuid PRIMARY KEY REFERENCES maintenance_requests(id),
    operation_id uuid NOT NULL,
    binding_hash text NOT NULL CHECK (binding_hash ~ '^[0-9a-f]{64}$'),
    held_until timestamptz NOT NULL
);

CREATE TABLE maintenance_assessment_destination_operations (
    operation_id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES maintenance_assessment_assignments(request_id),
    actor_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    command jsonb NOT NULL,
    receipt jsonb NOT NULL
);

CREATE TABLE maintenance_assessment_destinations (
    request_id uuid PRIMARY KEY REFERENCES maintenance_assessment_assignments(request_id),
    operation_id uuid NOT NULL UNIQUE REFERENCES maintenance_assessment_destination_operations(operation_id),
    request_revision integer NOT NULL CHECK (request_revision > 0),
    assignment_revision integer NOT NULL CHECK (assignment_revision > 0),
    revision integer NOT NULL CHECK (revision > 0),
    operator_id uuid,
    held_until timestamptz NOT NULL DEFAULT '-infinity'
);
