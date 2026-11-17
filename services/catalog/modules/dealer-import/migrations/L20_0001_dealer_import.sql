CREATE TABLE catalog_dealer_imports (
 operation_id text PRIMARY KEY CHECK(length(operation_id) BETWEEN 1 AND 128),
 actor_id uuid NOT NULL,
 organization_id uuid NOT NULL,
 digest text NOT NULL,
 result jsonb NOT NULL,
 revision integer NOT NULL DEFAULT 1 CHECK(revision=1),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE catalog_dealer_import_serials (
 serial_digest text PRIMARY KEY,
 listing_id uuid NOT NULL UNIQUE REFERENCES catalog_listings(id)
);

-- Imported identities remain private until canonical serial registration is integrated.
CREATE FUNCTION catalog_dealer_import_private_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status <> 'draft' AND EXISTS (
   SELECT 1 FROM catalog_dealer_import_serials WHERE listing_id=NEW.id
 ) THEN
   RAISE EXCEPTION 'Imported watch registration is unavailable. تسجيل الساعة المستوردة غير متاح.'
     USING ERRCODE='check_violation';
 END IF;
 RETURN NEW;
END;
$$;
CREATE TRIGGER catalog_dealer_import_private_guard BEFORE UPDATE ON catalog_listings
 FOR EACH ROW EXECUTE FUNCTION catalog_dealer_import_private_guard();
