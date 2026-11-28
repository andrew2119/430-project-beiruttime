-- Extend the sole journal; preserve the payment-only read boundary for existing consumers.
ALTER TABLE l08_orders ADD COLUMN financial_revision bigint NOT NULL DEFAULT 0 CHECK(financial_revision>=0);
CREATE TABLE l13_money_operations (
 id uuid PRIMARY KEY,
 order_id uuid NOT NULL REFERENCES l08_orders(id),
 kind text NOT NULL CHECK(kind IN ('refund','release','failed_authentication','job_fee')),
 request jsonb NOT NULL CHECK(jsonb_typeof(request)='object'),
 money jsonb NOT NULL CHECK(jsonb_typeof(money)='object'),
 amount_minor bigint NOT NULL CHECK(amount_minor>0 AND amount_minor<=18000000000000),
 recognized_fee_minor bigint NOT NULL DEFAULT 0 CHECK(recognized_fee_minor>=0 AND recognized_fee_minor<=18000000000000),
 fee_minor bigint NOT NULL CHECK(fee_minor>=0 AND fee_minor<=18000000000000),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','declined','confirmed')),
 sequence bigint NOT NULL DEFAULT 0 CHECK(sequence>=0),
 revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
 next_actor uuid NOT NULL,
 next_review_at timestamptz NOT NULL DEFAULT clock_timestamp()+interval '24 hours',
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX l13_one_fee_collection ON l13_money_operations(order_id)
 WHERE kind IN ('failed_authentication','job_fee') AND state<>'declined';
CREATE UNIQUE INDEX l13_one_release ON l13_money_operations(order_id)
 WHERE kind='release' AND state<>'declined';
CREATE TABLE l13_money_callbacks (
 event_id uuid PRIMARY KEY,
 operation_id uuid NOT NULL REFERENCES l13_money_operations(id),
 digest text NOT NULL,
 result jsonb NOT NULL,
 received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE l13_journal_groups RENAME TO l13_journal_postings;
ALTER TABLE l13_journal_postings ADD COLUMN movement_id uuid UNIQUE REFERENCES l13_money_operations(id);
ALTER TABLE l13_journal_postings ALTER COLUMN attempt_id DROP NOT NULL;
ALTER TABLE l13_journal_postings DROP CONSTRAINT l13_journal_groups_order_id_key;
ALTER TABLE l13_journal_postings ADD CONSTRAINT l13_posting_source CHECK((attempt_id IS NULL)<>(movement_id IS NULL));
CREATE UNIQUE INDEX l13_one_paid_group ON l13_journal_postings(order_id) WHERE movement_id IS NULL;
CREATE VIEW l13_journal_groups AS
 SELECT id,order_id,attempt_id,currency,total_minor,simulated,posted_at
 FROM l13_journal_postings WHERE movement_id IS NULL;
ALTER TABLE l13_journal_entries DROP CONSTRAINT l13_journal_entries_account_check;
ALTER TABLE l13_journal_entries ADD CONSTRAINT l13_journal_account CHECK(account IN
 ('simulated_clearing','buyer_held','fee_income','transport_payable','tax_payable'));

CREATE OR REPLACE FUNCTION l13_journal_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE gid uuid; posting record; operation record; entry_count bigint; balance numeric;
BEGIN
 IF TG_TABLE_NAME='l13_journal_postings' THEN gid := NEW.id; ELSE gid := NEW.group_id; END IF;
 SELECT * INTO posting FROM l13_journal_postings WHERE id=gid;
 SELECT count(*),sum(amount_minor) INTO entry_count,balance FROM l13_journal_entries WHERE group_id=gid;
 IF entry_count<2 OR balance IS DISTINCT FROM 0::numeric THEN
  RAISE EXCEPTION 'Journal must contain balanced entries';
 END IF;
 IF posting.movement_id IS NULL THEN
  IF entry_count<>2 OR NOT EXISTS(SELECT 1 FROM l13_journal_entries WHERE group_id=gid AND account='simulated_clearing' AND amount_minor=posting.total_minor)
   OR NOT EXISTS(SELECT 1 FROM l13_journal_entries WHERE group_id=gid AND account='buyer_held' AND amount_minor=-posting.total_minor) THEN
   RAISE EXCEPTION 'Journal must contain exactly balanced held-payment entries';
  END IF;
 ELSE
  SELECT * INTO operation FROM l13_money_operations WHERE id=posting.movement_id;
  IF operation.state<>'confirmed' OR operation.order_id<>posting.order_id OR operation.amount_minor<>posting.total_minor OR posting.currency<>'USD' THEN
   RAISE EXCEPTION 'Journal requires exact confirmed movement';
  END IF;
  IF operation.kind='refund' THEN
   IF (SELECT sum(recognized_fee_minor) FROM l13_money_operations WHERE order_id=operation.order_id AND kind='refund' AND state='confirmed')<>(CASE WHEN (SELECT sum(amount_minor) FROM l13_money_operations WHERE order_id=operation.order_id AND kind='refund' AND state='confirmed')=(operation.money->>'refundable_max_minor')::bigint THEN (operation.money->>'buyer_fee_minor')::bigint ELSE 0 END)
    OR entry_count<>(CASE WHEN operation.recognized_fee_minor>0 THEN 3 ELSE 2 END)
    OR (operation.recognized_fee_minor>0 AND NOT EXISTS(SELECT 1 FROM l13_journal_entries WHERE group_id=gid AND account='fee_income' AND amount_minor=-operation.recognized_fee_minor))
    OR NOT EXISTS(SELECT 1 FROM l13_journal_entries WHERE group_id=gid AND account='buyer_held' AND amount_minor=posting.total_minor+operation.recognized_fee_minor)
    OR NOT EXISTS(SELECT 1 FROM l13_journal_entries WHERE group_id=gid AND account='simulated_clearing' AND amount_minor=-posting.total_minor) THEN
    RAISE EXCEPTION 'Refund requires exact principal entries';
   END IF;
  ELSIF operation.kind IN ('failed_authentication','job_fee') THEN
   IF EXISTS(SELECT 1 FROM l13_journal_entries WHERE group_id=gid AND account NOT IN ('simulated_clearing','fee_income','transport_payable'))
    OR NOT EXISTS(SELECT 1 FROM l13_journal_entries WHERE group_id=gid AND account='simulated_clearing' AND amount_minor=posting.total_minor)
    OR (operation.fee_minor>0 AND NOT EXISTS(SELECT 1 FROM l13_journal_entries WHERE group_id=gid AND account='fee_income' AND amount_minor=-operation.fee_minor))
    OR (operation.fee_minor=0 AND EXISTS(SELECT 1 FROM l13_journal_entries WHERE group_id=gid AND account='fee_income')) THEN
    RAISE EXCEPTION 'Collection requires exact confirmed fee entries';
   END IF;
  ELSE
   IF NOT EXISTS(SELECT 1 FROM l13_journal_entries WHERE group_id=gid AND account='buyer_held' AND amount_minor=posting.total_minor)
    OR EXISTS(SELECT 1 FROM l13_journal_entries WHERE group_id=gid AND account<>'buyer_held' AND amount_minor>0) THEN
    RAISE EXCEPTION 'Release requires exact held funds';
   END IF;
  END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION l13_group_matches_attempt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.movement_id IS NOT NULL THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM l13_payment_attempts a JOIN l08_orders o ON o.id=a.order_id
  WHERE a.id=NEW.attempt_id AND a.order_id=NEW.order_id AND a.currency=NEW.currency AND a.total_minor=NEW.total_minor
   AND a.state='confirmed' AND o.state='paid_held' AND o.currency=NEW.currency AND o.total_minor=NEW.total_minor) THEN
  RAISE EXCEPTION 'Journal requires exact confirmed attempt and paid held order';
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION l13_money_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Money history cannot be deleted'; END IF;
 IF (NEW.id,NEW.order_id,NEW.kind,NEW.request,NEW.money,NEW.amount_minor,NEW.fee_minor,NEW.next_actor,NEW.created_at)
 IS DISTINCT FROM (OLD.id,OLD.order_id,OLD.kind,OLD.request,OLD.money,OLD.amount_minor,OLD.fee_minor,OLD.next_actor,OLD.created_at) THEN
  RAISE EXCEPTION 'Money operation bindings are immutable';
 END IF;
 IF OLD.state IN ('confirmed','declined') AND NEW IS DISTINCT FROM OLD THEN
  RAISE EXCEPTION 'Final money results cannot be replaced';
 END IF;
 IF NEW.recognized_fee_minor<>0 AND (NEW.kind<>'refund' OR NEW.state<>'confirmed') THEN
  RAISE EXCEPTION 'Buyer fee recognition requires a confirmed refund';
 END IF;
 IF NEW.sequence<=OLD.sequence OR NEW.revision<>OLD.revision+1 THEN
  RAISE EXCEPTION 'Money result sequence must advance';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l13_money_binding BEFORE UPDATE OR DELETE ON l13_money_operations FOR EACH ROW EXECUTE FUNCTION l13_money_immutable();
CREATE TRIGGER l13_money_callback_immutable BEFORE UPDATE OR DELETE ON l13_money_callbacks FOR EACH ROW EXECUTE FUNCTION l13_journal_immutable();

-- Current recovery assignments are provisioned by the authorized runtime boundary.
CREATE TABLE l13_payment_recovery_assignments (
 order_id uuid PRIMARY KEY REFERENCES l08_orders(id),
 operator_id uuid NOT NULL,
 assigned_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE FUNCTION l13_recovery_operator_independent() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM l08_orders WHERE id=NEW.order_id AND buyer_id=NEW.operator_id) THEN
  RAISE EXCEPTION 'Recovery operator must differ from buyer';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l13_recovery_operator_guard BEFORE INSERT OR UPDATE ON l13_payment_recovery_assignments
 FOR EACH ROW EXECUTE FUNCTION l13_recovery_operator_independent();
-- The authorized migration session supplies existing order assignments explicitly.
INSERT INTO l13_payment_recovery_assignments(order_id,operator_id)
 SELECT order_id,operator_id FROM jsonb_to_recordset(
  COALESCE(NULLIF(current_setting('bt.payment_recovery_assignments',true),''),'[]')::jsonb
 ) AS assignment(order_id uuid,operator_id uuid);
-- Validate every historic attempt too; missing backfill prevents activation.
ALTER TABLE l13_payment_attempts ADD CONSTRAINT l13_attempt_recovery_assignment
 FOREIGN KEY(order_id) REFERENCES l13_payment_recovery_assignments(order_id);
CREATE TABLE l13_money_reconciliations (
 event_id uuid PRIMARY KEY,
 operation_id uuid REFERENCES l13_money_operations(id),
 attempt_id uuid REFERENCES l13_payment_attempts(id),
 buyer_contact_id uuid,
 CHECK((operation_id IS NULL)<>(attempt_id IS NULL)),
 order_id uuid NOT NULL REFERENCES l08_orders(id),
 next_actor uuid NOT NULL,
 next_action text NOT NULL DEFAULT 'reconcile_original_movement'
  CHECK(next_action IN ('reconcile_original_movement','reconcile_original_payment')),
 CHECK(attempt_id IS NULL OR (next_action='reconcile_original_payment' AND next_actor<>buyer_contact_id)),
 next_review_at timestamptz NOT NULL DEFAULT clock_timestamp()+interval '24 hours',
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX l13_money_review_order ON l13_money_reconciliations(order_id);
CREATE TRIGGER l13_money_review_immutable BEFORE UPDATE OR DELETE ON l13_money_reconciliations
 FOR EACH ROW EXECUTE FUNCTION l13_journal_immutable();
CREATE FUNCTION l13_confirmed_movement_requires_journal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.state='confirmed' AND NOT EXISTS(
  SELECT 1 FROM l13_journal_postings WHERE movement_id=NEW.id AND order_id=NEW.order_id
   AND currency='USD' AND total_minor=NEW.amount_minor
 ) THEN RAISE EXCEPTION 'Confirmed movement requires exact journal posting'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER l13_confirmed_money_guard AFTER INSERT OR UPDATE ON l13_money_operations
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION l13_confirmed_movement_requires_journal();

-- Several conflicting attempts may be held; only one ordinary attempt may be open.
DROP INDEX l13_one_open_payment;
CREATE UNIQUE INDEX l13_one_open_payment ON l13_payment_attempts(order_id)
 WHERE state IN ('pending','confirmed');
