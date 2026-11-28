-- Retain the original serialized allocation time, never a retry-time price clock.
ALTER TABLE l13_order_quotes ADD CONSTRAINT l13_order_quote_pair UNIQUE(order_id,quote_id);
CREATE TABLE l13_quote_commitments (
 order_id uuid PRIMARY KEY REFERENCES l08_orders(id),
 quote_id uuid NOT NULL UNIQUE,
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','acknowledged','reconciliation')),
 lease uuid,
 lease_until timestamptz,
 attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 last_error text,
 next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 acknowledged_at timestamptz,
 follow_up_at timestamptz NOT NULL DEFAULT clock_timestamp()+interval '24 hours',
 escalate_at timestamptz NOT NULL DEFAULT clock_timestamp()+interval '48 hours',
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(order_id,quote_id) REFERENCES l13_order_quotes(order_id,quote_id),
 CHECK((state='acknowledged')=(acknowledged_at IS NOT NULL))
);
CREATE INDEX l13_quote_commit_pending ON l13_quote_commitments(next_attempt_at) WHERE state='pending';
CREATE FUNCTION l13_quote_commit_binding_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Retained quote commitment history cannot be deleted';
 END IF;
 IF (NEW.order_id,NEW.quote_id,NEW.payload,NEW.created_at,NEW.follow_up_at,NEW.escalate_at)
 IS DISTINCT FROM (OLD.order_id,OLD.quote_id,OLD.payload,OLD.created_at,OLD.follow_up_at,OLD.escalate_at) THEN
  RAISE EXCEPTION 'Original quote commitment bindings are immutable';
 END IF;
 IF OLD.state<>'pending' AND NEW IS DISTINCT FROM OLD THEN
  RAISE EXCEPTION 'A final quote commitment receipt cannot be replaced';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l13_quote_commit_immutable BEFORE UPDATE OR DELETE ON l13_quote_commitments
 FOR EACH ROW EXECUTE FUNCTION l13_quote_commit_binding_immutable();
