CREATE TABLE technical_intakes (
 id uuid PRIMARY KEY, organization_id uuid NOT NULL, order_id uuid NOT NULL, author_id uuid NOT NULL,
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0),
 state text NOT NULL CHECK(state IN ('awaiting_intake','received')),
 custody_receipt_id uuid, custody_revision integer, received_at timestamptz,
 private_record jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(organization_id,order_id),
 CHECK((state='awaiting_intake' AND custody_receipt_id IS NULL AND received_at IS NULL) OR
 (state='received' AND custody_receipt_id IS NOT NULL AND custody_revision>0 AND received_at IS NOT NULL))
);
CREATE INDEX technical_intakes_org ON technical_intakes(organization_id,updated_at,id);
CREATE TABLE technical_intake_operations (
 actor_id uuid NOT NULL, organization_id uuid NOT NULL, key text NOT NULL, request_hash text NOT NULL, result jsonb NOT NULL,
 PRIMARY KEY(actor_id,organization_id,key)
);
CREATE TABLE technical_intake_audit (
 id uuid PRIMARY KEY, record_id uuid NOT NULL REFERENCES technical_intakes(id), actor_id uuid NOT NULL,
 revision integer NOT NULL, state text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(record_id,revision)
);
