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
-- Like the migration ledger, the runtime role may read the record but never write it.
DO $$
DECLARE runtime text := left(current_user, length(current_user) - 6);
BEGIN
 IF right(current_user, 6) = '_owner' AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = runtime) THEN
  EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON demo_seed_rows FROM %I', runtime);
 END IF;
END $$;
-- Identity's signed handoffs, as Catalog received them. The runtime role may read this table and call
-- demo_seed_receive() below, the one way a receipt is written: it may never insert, edit or delete a row.
-- Removal deletes only the receipts, and their ingress entries, that the function recorded in demo_seed_rows.
-- seq is Identity's producer order and assertion Identity's RS256 signature over exactly the receipt's fields,
-- made with the seed's own handoff key; Catalog's owner-run seed step verifies it before it writes anything.
CREATE TABLE demo_seed_handoffs (
 event_id uuid PRIMARY KEY,
 sample_set text NOT NULL CHECK (sample_set IN ('demo', 'click-test')),
 holder text NOT NULL CHECK (holder IN ('seller', 'staff')),
 subject_id uuid NOT NULL,
 business_id uuid,
 state text NOT NULL CHECK (state IN ('ready', 'withdrawn')),
 seq bigint NOT NULL CHECK (seq > 0),
 issued_at timestamptz NOT NULL,
 assertion text NOT NULL CHECK (length(assertion) BETWEEN 1 AND 4096),
 received_at timestamptz NOT NULL DEFAULT now(),
 CHECK ((holder = 'staff') = (business_id IS NOT NULL)),
 UNIQUE (sample_set, holder, seq)
);
-- The newest handoff Catalog has received for each set and holder, by Identity's order: written only by
-- demo_seed_receive(), and it only ever moves forward. The seed acts only on the receipt it names, so a newest
-- receipt that is lost, replaced or fails its signature check refuses; an older one never counts again. Removal
-- keeps it, so a late redelivery of an older handoff cannot become current after a removal either.
CREATE TABLE demo_seed_handoff_marks (
 sample_set text NOT NULL CHECK (sample_set IN ('demo', 'click-test')),
 holder text NOT NULL CHECK (holder IN ('seller', 'staff')),
 seq bigint NOT NULL CHECK (seq > 0),
 event_id uuid NOT NULL,
 PRIMARY KEY (sample_set, holder)
);
-- Runs as this migration's owner. Under the seed's shared lock, so never while a removal runs, and under the
-- holder's own lock (demo_seed.holder_lock), so never while a seed step is checking or writing for that holder,
-- both taken without waiting (55P03, so 409 and Identity's relay retries). It stores one receipt only when it
-- names exactly one of the four pinned set, holder, account and business tuples, with an order and an assertion,
-- and only in the transaction whose ingress entry for the event it is (the inbox row this transaction wrote);
-- an order another event already holds for that holder is refused. It moves the holder's mark forward, never
-- back, then records that receipt and that inbox row under the holder's handoff key. It cannot check the
-- signature: a receipt it stores is only a candidate, which the seed step verifies before it writes anything.
-- Its creation times use demo_seed.BORN_FORMAT.
CREATE FUNCTION demo_seed_receive(received_event uuid, set_name text, holder_name text, subject uuid, business uuid,
                                  handoff_state text, issued timestamptz, handoff_seq bigint,
                                  handoff_assertion text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
SET "TimeZone" = 'UTC'
SET "DateStyle" = 'ISO, YMD'
AS $$
DECLARE
 seed_key text;
 claimed uuid;
BEGIN
 IF NOT pg_try_advisory_xact_lock_shared(hashtextextended('demo-seed', 0)) THEN
  RAISE EXCEPTION 'A demo seed removal is running' USING ERRCODE = '55P03';
 END IF;
 IF handoff_state IS NULL OR handoff_state NOT IN ('ready', 'withdrawn') OR issued IS NULL
     OR handoff_seq IS NULL OR handoff_seq < 1
     OR handoff_assertion IS NULL OR length(handoff_assertion) NOT BETWEEN 1 AND 4096 OR NOT EXISTS (
     SELECT 1 FROM (VALUES
       ('demo', 'seller', 'b8151b1f-a571-55cf-9b20-0d266c309882'::uuid, NULL::uuid),
       ('demo', 'staff', '27fe364e-a31a-5e87-bd1b-5849dd4a217c'::uuid, '392b6fec-314f-59b9-b572-43ff7ff349bd'::uuid),
       ('click-test', 'seller', '9489caa0-ab50-5674-bd38-dd896d3d5f72'::uuid, NULL::uuid),
       ('click-test', 'staff', '2b35cdec-1c4c-5196-a772-b7db3c3e7400'::uuid, 'fe3eea0b-92f2-5c16-9b01-9a0fd0e54f13'::uuid)
     ) AS pinned (pinned_set, pinned_holder, pinned_subject, pinned_business)
     WHERE pinned_set = set_name AND pinned_holder = holder_name AND pinned_subject = subject
       AND pinned_business IS NOT DISTINCT FROM business) THEN
  RAISE EXCEPTION 'Not a demo seed handoff' USING ERRCODE = '22023';
 END IF;
 IF NOT pg_try_advisory_xact_lock(hashtextextended('demo-seed-handoff:' || set_name || ':' || holder_name, 0)) THEN
  RAISE EXCEPTION 'A demo seed step is checking this holder' USING ERRCODE = '55P03';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM inbox WHERE consumer = 'catalog.moderation.v1' AND event_id = received_event
     AND xmin::text::bigint = pg_current_xact_id()::text::bigint % 4294967296) THEN
  RAISE EXCEPTION 'A handoff is received only through the event ingress' USING ERRCODE = '22023';
 END IF;
 SELECT h.event_id INTO claimed FROM demo_seed_handoffs h
  WHERE h.sample_set = set_name AND h.holder = holder_name AND h.seq = handoff_seq;
 IF claimed IS NOT NULL AND claimed <> received_event THEN
  RAISE EXCEPTION 'Another handoff holds this order' USING ERRCODE = '22023';
 END IF;
 INSERT INTO demo_seed_handoffs (event_id, sample_set, holder, subject_id, business_id, state, seq, issued_at,
                                 assertion)
 VALUES (received_event, set_name, holder_name, subject, business, handoff_state, handoff_seq, issued,
         handoff_assertion)
 ON CONFLICT (event_id) DO NOTHING;
 IF NOT FOUND THEN
  RETURN;
 END IF;
 INSERT INTO demo_seed_handoff_marks AS m (sample_set, holder, seq, event_id)
 VALUES (set_name, holder_name, handoff_seq, received_event)
 ON CONFLICT (sample_set, holder) DO UPDATE SET seq = excluded.seq, event_id = excluded.event_id
 WHERE m.seq < excluded.seq;
 seed_key := 'DEMO-SEED-' || upper(set_name) || '-HANDOFF-' || upper(holder_name);
 -- An earlier entry at the same key is stale, since a row could be inserted there: replace it, as record() does.
 DELETE FROM demo_seed_rows WHERE (table_name, row_key) IN (
  ('demo_seed_handoffs', jsonb_build_object('event_id', received_event::text)),
  ('inbox', jsonb_build_object('consumer', 'catalog.moderation.v1', 'event_id', received_event::text)));
 INSERT INTO demo_seed_rows (demo_key, table_name, row_key, born)
 SELECT seed_key, 'demo_seed_handoffs', jsonb_build_object('event_id', h.event_id::text),
  'created:' || coalesce(to_char(h.received_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), '')
 FROM demo_seed_handoffs h WHERE h.event_id = received_event;
 INSERT INTO demo_seed_rows (demo_key, table_name, row_key, born)
 SELECT seed_key, 'inbox', jsonb_build_object('consumer', i.consumer, 'event_id', i.event_id::text),
  'created:' || coalesce(to_char(i.received_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), '')
 FROM inbox i WHERE i.consumer = 'catalog.moderation.v1' AND i.event_id = received_event;
END $$;
REVOKE ALL ON FUNCTION demo_seed_receive(uuid, text, text, uuid, uuid, text, timestamptz, bigint, text) FROM PUBLIC;
DO $$
DECLARE runtime text := left(current_user, length(current_user) - 6);
BEGIN
 IF right(current_user, 6) = '_owner' AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = runtime) THEN
  EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON demo_seed_handoffs FROM %I', runtime);
  EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON demo_seed_handoff_marks FROM %I', runtime);
  EXECUTE format('GRANT EXECUTE ON FUNCTION demo_seed_receive(uuid, text, text, uuid, uuid, text, timestamptz, '
                 'bigint, text) TO %I', runtime);
 END IF;
END $$;
