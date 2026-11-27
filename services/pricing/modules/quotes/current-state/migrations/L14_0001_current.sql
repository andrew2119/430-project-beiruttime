CREATE TABLE l14_pricing_operations (
 id uuid PRIMARY KEY, actor_id uuid NOT NULL, organization_id uuid,
 operation_key text NOT NULL CHECK(length(operation_key) BETWEEN 8 AND 128),
 request_hash text NOT NULL, result jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), UNIQUE(actor_id,operation_key)
);
CREATE TABLE l14_assessed_quotes (
 id uuid PRIMARY KEY, kind text NOT NULL CHECK(kind IN ('brand','repair')),
 source_id uuid NOT NULL, source_revision bigint NOT NULL CHECK(source_revision>0),
 buyer_id uuid NOT NULL, organization_id uuid NOT NULL, author_id uuid NOT NULL,
 revision bigint NOT NULL CHECK(revision>0), snapshot jsonb NOT NULL,
 state text NOT NULL DEFAULT 'issued' CHECK(state IN ('issued','accepted','superseded','declined_return_held','expired_return_held')),
 expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(kind,source_id,revision)
);
CREATE UNIQUE INDEX l14_one_current_quote ON l14_assessed_quotes(kind,source_id) WHERE state IN ('issued','accepted');
CREATE INDEX l14_quote_buyer ON l14_assessed_quotes(buyer_id,created_at DESC);
CREATE INDEX l14_quote_org ON l14_assessed_quotes(organization_id,created_at DESC);
CREATE TABLE l14_quote_decisions (
 quote_id uuid PRIMARY KEY REFERENCES l14_assessed_quotes(id), actor_id uuid NOT NULL,
 decision text NOT NULL CHECK(decision IN ('accepted','declined_return_held')),
 selected_line_ids jsonb NOT NULL, amounts jsonb NOT NULL,
 terms_digest text NOT NULL, decided_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE FUNCTION l14_quote_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.id,NEW.kind,NEW.source_id,NEW.source_revision,NEW.buyer_id,NEW.organization_id,
     NEW.author_id,NEW.revision,NEW.snapshot,NEW.expires_at,NEW.created_at)
 IS DISTINCT FROM (OLD.id,OLD.kind,OLD.source_id,OLD.source_revision,OLD.buyer_id,OLD.organization_id,
     OLD.author_id,OLD.revision,OLD.snapshot,OLD.expires_at,OLD.created_at) THEN
   RAISE EXCEPTION 'assessed_quote_snapshot_immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER l14_quote_snapshot_guard BEFORE UPDATE ON l14_assessed_quotes FOR EACH ROW EXECUTE FUNCTION l14_quote_immutable();
