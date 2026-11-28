CREATE TABLE maintenance_received_cases (
    case_id uuid PRIMARY KEY REFERENCES technical_intakes(id),
    request_id uuid NOT NULL UNIQUE REFERENCES maintenance_requests(id),
    fee_quote_id uuid NOT NULL,
    fee_quote_revision integer NOT NULL CHECK(fee_quote_revision > 0)
);
