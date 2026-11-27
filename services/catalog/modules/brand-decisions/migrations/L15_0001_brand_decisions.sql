CREATE TABLE catalog_brand_decisions (
 -- Request scope is verified under the Catalog request lock by every command.
 -- No cross-module FK: this additive schema is independent of module loading order.
 id uuid PRIMARY KEY, request_id uuid NOT NULL, request_revision integer NOT NULL,
 actor_id uuid NOT NULL, brand_id uuid NOT NULL, operation_key text NOT NULL,
 digest text NOT NULL, intent jsonb NOT NULL, bindings jsonb,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','denied')),
 code text, created_at timestamptz NOT NULL DEFAULT now(), confirmed_at timestamptz,
 UNIQUE(actor_id,operation_key)
);
CREATE UNIQUE INDEX catalog_one_brand_decision ON catalog_brand_decisions(request_id,request_revision) WHERE status IN ('pending','approved','rejected');
