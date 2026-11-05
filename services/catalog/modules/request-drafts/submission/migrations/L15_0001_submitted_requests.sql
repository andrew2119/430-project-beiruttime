ALTER TABLE l08_request_drafts ADD COLUMN submitted_request_id uuid;
CREATE TABLE catalog_customization_requests (
 id uuid PRIMARY KEY, draft_id uuid NOT NULL UNIQUE REFERENCES l08_request_drafts(id), buyer_id uuid NOT NULL,
 brand_id uuid NOT NULL, revision integer NOT NULL DEFAULT 1 CHECK(revision>0), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX catalog_requests_buyer ON catalog_customization_requests(buyer_id,created_at DESC);
CREATE INDEX catalog_requests_brand ON catalog_customization_requests(brand_id,created_at DESC);
CREATE TABLE catalog_customization_revisions (
 request_id uuid NOT NULL REFERENCES catalog_customization_requests(id), revision integer NOT NULL,
 configuration_digest text NOT NULL, configuration jsonb NOT NULL, content jsonb NOT NULL,
 actor_id uuid NOT NULL, reason text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(request_id,revision)
);
CREATE FUNCTION catalog_immutable_request_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Customization request revisions are immutable'; END $$;
CREATE TRIGGER catalog_request_revision_immutable BEFORE UPDATE OR DELETE ON catalog_customization_revisions
FOR EACH ROW EXECUTE FUNCTION catalog_immutable_request_revision();
CREATE TABLE catalog_customization_operations (
 id uuid PRIMARY KEY, request_id uuid NOT NULL REFERENCES catalog_customization_requests(id), actor_id uuid NOT NULL,
 operation_key text NOT NULL, digest text NOT NULL, result jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(actor_id,operation_key)
);
