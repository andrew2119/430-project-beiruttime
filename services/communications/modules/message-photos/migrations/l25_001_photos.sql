CREATE TABLE IF NOT EXISTS l25_photos(
              id TEXT PRIMARY KEY, actor TEXT, business TEXT, thread TEXT, watch TEXT,
              source_revision INTEGER, created INTEGER, attached INTEGER, bytes BLOB,
              width INTEGER, height INTEGER);
            CREATE TABLE IF NOT EXISTS l25_operations(
              id TEXT PRIMARY KEY, actor TEXT, business TEXT, thread TEXT, watch TEXT,
              fingerprint TEXT, result TEXT);
            CREATE TABLE IF NOT EXISTS l25_outbox(
              operation TEXT PRIMARY KEY, event TEXT);
