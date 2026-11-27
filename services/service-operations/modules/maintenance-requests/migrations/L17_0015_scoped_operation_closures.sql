CREATE TABLE maintenance_preference_closures (
    operation_id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES maintenance_requests(id),
    buyer_id uuid NOT NULL
);
CREATE TABLE maintenance_acknowledgement_closures (
    operation_id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES maintenance_requests(id),
    actor_id uuid NOT NULL,
    organization_id uuid NOT NULL
);
CREATE TABLE service_diagnosis_closures (
    operation_id uuid PRIMARY KEY,
    case_id uuid NOT NULL REFERENCES technical_intakes(id),
    actor_id uuid NOT NULL,
    organization_id uuid NOT NULL
);
