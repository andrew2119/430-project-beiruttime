-- Ownership record of the deploy demo seed: one row per row the seed itself inserted, by table and primary key.
-- Removal deletes exactly these rows; the seed treats any pinned id or address without an entry here as foreign.
CREATE TABLE demo_seed_rows (
 step bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 demo_key text NOT NULL CHECK (demo_key ~ '^DEMO-SEED-[A-Z0-9-]+$'),
 table_name text NOT NULL CHECK (table_name ~ '^[a-z][a-z0-9_]*$'),
 row_key jsonb NOT NULL CHECK (jsonb_typeof(row_key) = 'object'),
 -- The row's incarnation when the seed inserted it: its creation time, or for a table without one its whole
 -- text. Removal deletes a recorded key only while the row there still has this value.
 born text NOT NULL CHECK (born ~ '^(created|row):'),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (table_name, row_key)
);
-- Identity's producer order for its demo seed handoffs to Catalog: each handoff takes the next value, and the
-- handoff and removal steps that draw it never overlap, so a later handoff always has the higher one. Catalog
-- decides which handoff is current by this order, never by a clock. Only the seed, as this migration's owner,
-- draws from it.
CREATE SEQUENCE demo_seed_handoff_seq AS bigint MINVALUE 1 NO CYCLE;
-- Like the migration ledger, the runtime role may read the record but never write it, and it may not use the
-- handoff order at all.
DO $$
DECLARE runtime text := left(current_user, length(current_user) - 6);
BEGIN
 IF right(current_user, 6) = '_owner' AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = runtime) THEN
  EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON demo_seed_rows FROM %I', runtime);
  EXECUTE format('REVOKE ALL ON SEQUENCE demo_seed_handoff_seq FROM %I', runtime);
 END IF;
END $$;
REVOKE ALL ON SEQUENCE demo_seed_handoff_seq FROM PUBLIC;
