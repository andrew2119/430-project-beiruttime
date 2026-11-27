CREATE TABLE l13_journal_groups (
 id uuid PRIMARY KEY,
 order_id uuid NOT NULL UNIQUE REFERENCES l08_orders(id),
 attempt_id uuid NOT NULL UNIQUE,
 currency text NOT NULL CHECK(currency IN ('USD','LBP')),
 total_minor bigint NOT NULL CHECK(total_minor>0 AND total_minor<=9000000000000000),
 simulated boolean NOT NULL DEFAULT true CHECK(simulated),
 posted_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE l13_journal_entries (
 group_id uuid NOT NULL REFERENCES l13_journal_groups(id),
 account text NOT NULL CHECK(account IN ('simulated_clearing','buyer_held')),
 amount_minor bigint NOT NULL CHECK(amount_minor<>0 AND abs(amount_minor)<=9000000000000000),
 PRIMARY KEY(group_id,account)
);
CREATE FUNCTION l13_journal_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Posted journal records are immutable'; END $$;
CREATE TRIGGER l13_group_immutable BEFORE UPDATE OR DELETE ON l13_journal_groups FOR EACH ROW EXECUTE FUNCTION l13_journal_immutable();
CREATE TRIGGER l13_entry_immutable BEFORE UPDATE OR DELETE ON l13_journal_entries FOR EACH ROW EXECUTE FUNCTION l13_journal_immutable();
CREATE FUNCTION l13_journal_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE gid uuid; total bigint; clearing bigint; held bigint; entry_count bigint;
BEGIN
 IF TG_TABLE_NAME='l13_journal_groups' THEN
  gid := NEW.id;
 ELSE
  gid := NEW.group_id;
 END IF;
 SELECT total_minor INTO total FROM l13_journal_groups WHERE id=gid;
 SELECT count(*),sum(amount_minor) FILTER(WHERE account='simulated_clearing'),sum(amount_minor) FILTER(WHERE account='buyer_held')
 INTO entry_count,clearing,held FROM l13_journal_entries WHERE group_id=gid;
 IF entry_count<>2 OR clearing IS DISTINCT FROM total OR held IS DISTINCT FROM -total THEN
  RAISE EXCEPTION 'Journal must contain exactly balanced held-payment entries';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER l13_group_balance AFTER INSERT ON l13_journal_groups DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION l13_journal_balanced();
CREATE CONSTRAINT TRIGGER l13_entry_balance AFTER INSERT ON l13_journal_entries DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION l13_journal_balanced();
