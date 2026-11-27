CREATE TABLE catalog_compatibility_rules (
 id uuid NOT NULL, brand_id uuid NOT NULL, revision integer NOT NULL CHECK(revision>0),
 base_model text NOT NULL, caliber text NOT NULL, mounting jsonb NOT NULL, option_revisions jsonb NOT NULL, option_ids uuid[] NOT NULL CHECK(cardinality(option_ids)=5),
 status text NOT NULL CHECK(status IN ('valid','incompatible','parts_unavailable','manual_assessment')),
 reason text NOT NULL, actor_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(id,revision)
);
CREATE INDEX catalog_compatibility_brand ON catalog_compatibility_rules(brand_id,base_model,caliber);
