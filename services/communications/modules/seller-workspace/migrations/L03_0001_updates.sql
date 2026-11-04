CREATE TABLE seller_workspace_updates (
 listing_id uuid PRIMARY KEY,
 seller_id uuid NOT NULL,
 organization_id uuid,
 revision integer NOT NULL CHECK(revision>0),
 event_type text NOT NULL,
 occurred_at timestamptz NOT NULL,
 received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX seller_workspace_updates_owner ON seller_workspace_updates(seller_id,received_at DESC);
CREATE INDEX seller_workspace_updates_org ON seller_workspace_updates(organization_id,received_at DESC) WHERE organization_id IS NOT NULL;
