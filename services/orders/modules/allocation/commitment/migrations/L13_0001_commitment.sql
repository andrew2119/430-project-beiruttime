-- Additive; legacy fences remain committed until reconciled, never silently reusable.
ALTER TABLE l08_watches DROP CONSTRAINT l08_watches_status_check;
ALTER TABLE l08_watches ADD CONSTRAINT l08_watches_status_check CHECK(status IN ('available','reserved','fenced','editing','withdrawn'));
ALTER TABLE l08_watches ADD COLUMN seller_type text CHECK(seller_type IN ('private','dealer','brand'));
ALTER TABLE l08_watches ADD COLUMN auction_committed boolean NOT NULL DEFAULT true;
ALTER TABLE l08_watches ADD COLUMN source_kind text;
ALTER TABLE l08_orders DROP CONSTRAINT l08_orders_state_check;
ALTER TABLE l08_orders ADD CONSTRAINT l08_orders_state_check CHECK(state IN ('awaiting_payment','payment_unknown','expired_fenced','paid_held'));
CREATE TABLE l13_order_quotes (
 order_id uuid PRIMARY KEY REFERENCES l08_orders(id),
 quote_id uuid NOT NULL UNIQUE,
 quote_revision bigint NOT NULL CHECK(quote_revision>0),
 listing_revision bigint NOT NULL CHECK(listing_revision>0),
 seller_type text NOT NULL CHECK(seller_type IN ('private','dealer','brand')),
 snapshot jsonb NOT NULL,
 retained_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE FUNCTION l13_retained_quote_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Retained exact quotes are immutable'; END $$;
CREATE TRIGGER l13_quote_immutable BEFORE UPDATE OR DELETE ON l13_order_quotes FOR EACH ROW EXECUTE FUNCTION l13_retained_quote_immutable();
