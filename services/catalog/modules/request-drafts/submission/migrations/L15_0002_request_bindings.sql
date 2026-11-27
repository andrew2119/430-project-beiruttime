ALTER TABLE catalog_customization_requests
 ADD COLUMN watch_id uuid,
 ADD COLUMN recovery_operator_id uuid,
 ADD COLUMN assessor_id uuid,
 ADD COLUMN approver_id uuid,
 ADD COLUMN quality_reviewer_id uuid,
 ADD COLUMN binding_revision integer NOT NULL DEFAULT 0 CHECK (binding_revision >= 0),
 ADD CONSTRAINT catalog_request_assignment_independence CHECK (
  (recovery_operator_id IS NULL AND assessor_id IS NULL AND approver_id IS NULL AND quality_reviewer_id IS NULL)
  OR (watch_id IS NOT NULL AND recovery_operator_id IS NOT NULL AND assessor_id IS NOT NULL
      AND approver_id IS NOT NULL AND quality_reviewer_id IS NOT NULL
      AND assessor_id <> approver_id AND assessor_id <> quality_reviewer_id
      AND approver_id <> quality_reviewer_id AND buyer_id <> assessor_id
      AND buyer_id <> approver_id AND buyer_id <> quality_reviewer_id AND buyer_id <> recovery_operator_id)
 );
CREATE TABLE catalog_request_binding_history (
 request_id uuid NOT NULL REFERENCES catalog_customization_requests(id),
 binding_revision integer NOT NULL CHECK (binding_revision > 0),
 producer text NOT NULL CHECK (producer IN ('orders','service-operations')),
 operation_id uuid NOT NULL,
 source_revision integer NOT NULL CHECK (source_revision > 0),
 digest text NOT NULL,
 command jsonb NOT NULL,
 result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(request_id,binding_revision),
 UNIQUE(producer,operation_id),
 UNIQUE(request_id,producer,source_revision)
);
CREATE TRIGGER catalog_request_binding_immutable BEFORE UPDATE OR DELETE ON catalog_request_binding_history
 FOR EACH ROW EXECUTE FUNCTION catalog_immutable_request_revision();
