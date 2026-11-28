-- Private single-use challenge and operation receipt storage.
CREATE TABLE IF NOT EXISTS l22_external_operations (
            operation_id TEXT PRIMARY KEY, browser_hash TEXT NOT NULL,
            actor_id TEXT, organization_id TEXT, expected_revision INTEGER NOT NULL,
            state_hash TEXT NOT NULL, nonce_hash TEXT NOT NULL,
            issuer TEXT NOT NULL, audience TEXT NOT NULL,
            created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'ready',
            request_hash TEXT, binding TEXT, subject_id TEXT,
            revision INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS l22_external_browser_created
    ON l22_external_operations(browser_hash, created_at);
