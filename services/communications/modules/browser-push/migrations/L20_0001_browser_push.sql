PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS l20_push_devices(
          id TEXT PRIMARY KEY, capability TEXT NOT NULL, actor TEXT NOT NULL,
          session TEXT NOT NULL, access_revision INTEGER NOT NULL,
          revision INTEGER NOT NULL, active INTEGER NOT NULL, subscription TEXT);
        CREATE TABLE IF NOT EXISTS l20_push_receipts(
          operation TEXT PRIMARY KEY, actor TEXT NOT NULL, session TEXT NOT NULL,
          fingerprint TEXT NOT NULL, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS l20_push_deliveries(
          notice TEXT NOT NULL, device TEXT NOT NULL, revision INTEGER NOT NULL,
          attempts INTEGER NOT NULL, state TEXT NOT NULL,
          PRIMARY KEY(notice,device,revision));

CREATE TABLE IF NOT EXISTS l20_push_revoked_sessions(actor TEXT NOT NULL, session TEXT NOT NULL, PRIMARY KEY(actor,session));
