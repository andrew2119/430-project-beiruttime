-- Receipts describe a concluded release; they never authorize another allocation.
CREATE TABLE l13_unpaid_release_receipts (
 order_id uuid PRIMARY KEY REFERENCES l08_orders(id),
 watch_id uuid NOT NULL REFERENCES l08_watches(id),
 order_revision bigint NOT NULL CHECK(order_revision>0),
 released_at timestamptz NOT NULL,
 attempt_count integer NOT NULL CHECK(attempt_count>=0),
 origin text NOT NULL CHECK(origin IN ('expiry','historical')),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE FUNCTION l13_release_receipt_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Unpaid release receipts are immutable'; END $$;
CREATE TRIGGER l13_release_receipt_immutable BEFORE UPDATE OR DELETE ON l13_unpaid_release_receipts
 FOR EACH ROW EXECUTE FUNCTION l13_release_receipt_immutable();
CREATE TABLE l13_job_bindings (
 order_id uuid PRIMARY KEY REFERENCES l08_orders(id),
 binding jsonb NOT NULL,
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TRIGGER l13_job_binding_immutable BEFORE UPDATE OR DELETE ON l13_job_bindings
 FOR EACH ROW EXECUTE FUNCTION l13_release_receipt_immutable();
