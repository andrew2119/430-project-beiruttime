CREATE TABLE maintenance_request_photos (
    photo_ref uuid PRIMARY KEY,
    actor_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    watch_id uuid NOT NULL,
    request_operation_id uuid NOT NULL,
    upload_operation_id uuid NOT NULL,
    request_hash text NOT NULL,
    media_type text NOT NULL CHECK (media_type IN ('image/jpeg', 'image/png', 'image/webp')),
    content bytea CHECK (octet_length(content) BETWEEN 1 AND 262144),
    uploaded_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK (expires_at > uploaded_at),
    request_id uuid REFERENCES maintenance_requests(id),
    CHECK (request_id IS NULL OR content IS NOT NULL),
    UNIQUE (request_operation_id, actor_id, organization_id, upload_operation_id)
);

CREATE INDEX maintenance_request_photos_expiry ON maintenance_request_photos (expires_at)
WHERE request_id IS NULL AND content IS NOT NULL;
