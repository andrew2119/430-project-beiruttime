CREATE TABLE l13_payment_attempts (
 id uuid PRIMARY KEY,
 order_id uuid NOT NULL REFERENCES l08_orders(id),
 buyer_id uuid NOT NULL,
 quote_id uuid NOT NULL,
 quote_revision bigint NOT NULL CHECK(quote_revision>0),
 currency text NOT NULL CHECK(currency IN ('USD','LBP')),
 total_minor bigint NOT NULL CHECK(total_minor>0 AND total_minor<=9000000000000000),
 route text NOT NULL CHECK(route IN ('card','whish','omt')),
 reference text NOT NULL UNIQUE,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','declined','confirmed','held')),
 sequence bigint NOT NULL DEFAULT 0 CHECK(sequence>=0),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX l13_one_open_payment ON l13_payment_attempts(order_id) WHERE state IN ('pending','confirmed','held');
CREATE TABLE l13_payment_callbacks (
 event_id uuid PRIMARY KEY,
 attempt_id uuid NOT NULL REFERENCES l13_payment_attempts(id),
 digest text NOT NULL,
 outcome jsonb NOT NULL,
 received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE FUNCTION l13_attempt_binding_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.order_id,NEW.buyer_id,NEW.quote_id,NEW.quote_revision,NEW.currency,NEW.total_minor,NEW.route,NEW.reference)
 IS DISTINCT FROM (OLD.order_id,OLD.buyer_id,OLD.quote_id,OLD.quote_revision,OLD.currency,OLD.total_minor,OLD.route,OLD.reference) THEN
  RAISE EXCEPTION 'Payment attempt bindings are immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l13_attempt_binding BEFORE UPDATE ON l13_payment_attempts FOR EACH ROW EXECUTE FUNCTION l13_attempt_binding_immutable();
ALTER TABLE l13_journal_groups ADD CONSTRAINT l13_group_attempt_fk FOREIGN KEY(attempt_id) REFERENCES l13_payment_attempts(id);
CREATE FUNCTION l13_group_matches_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM l13_payment_attempts a JOIN l08_orders o ON o.id=a.order_id
  WHERE a.id=NEW.attempt_id AND a.order_id=NEW.order_id AND a.currency=NEW.currency AND a.total_minor=NEW.total_minor
   AND a.state='confirmed' AND o.state='paid_held' AND o.currency=NEW.currency AND o.total_minor=NEW.total_minor) THEN
  RAISE EXCEPTION 'Journal requires exact confirmed attempt and paid held order';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER l13_group_attempt_binding AFTER INSERT ON l13_journal_groups DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION l13_group_matches_attempt();
-- Paid requires the one actual group; untrusted generic transitions cannot manufacture it.
CREATE FUNCTION l13_paid_requires_journal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.state='paid_held' AND NOT EXISTS(SELECT 1 FROM l13_journal_groups WHERE order_id=NEW.id AND total_minor=NEW.total_minor AND currency=NEW.currency) THEN
  RAISE EXCEPTION 'Paid requires an exact balanced journal group';
 END IF;
 IF TG_OP='UPDATE' AND OLD.state='paid_held' AND NEW.state<>'paid_held' THEN
  RAISE EXCEPTION 'Paid funds cannot be released through ordinary state updates';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l13_paid_guard BEFORE INSERT OR UPDATE ON l08_orders FOR EACH ROW EXECUTE FUNCTION l13_paid_requires_journal();
