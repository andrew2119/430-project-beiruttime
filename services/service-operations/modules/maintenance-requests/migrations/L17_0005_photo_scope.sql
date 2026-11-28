ALTER TABLE maintenance_request_photos
    ADD COLUMN brand_id uuid,
    ADD COLUMN intervention text CHECK (intervention IN ('limited_maintenance', 'overhaul_assessment')),
    ADD COLUMN watch_revision numeric CHECK (watch_revision > 0),
    ADD COLUMN capability_revision numeric CHECK (capability_revision > 0),
    ADD COLUMN policy_revision numeric CHECK (policy_revision > 0);

-- Earlier unattached uploads have no verifiable scope. Keep their operation keys.
UPDATE maintenance_request_photos SET content = NULL WHERE request_id IS NULL;

ALTER TABLE maintenance_request_photos ADD CONSTRAINT maintenance_photo_scope_required CHECK (
    request_id IS NOT NULL OR content IS NULL OR (
        brand_id IS NOT NULL AND intervention IS NOT NULL AND watch_revision IS NOT NULL
        AND capability_revision IS NOT NULL AND policy_revision IS NOT NULL
    )
);
